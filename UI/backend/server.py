"""Tokenizers expo demo: frontend + agentic pipeline + Qwen3-14B on ONE port.

    /                    -> UI/frontend/index.html (+ logo.jpg)
    /api/...             -> live consultation sessions, saved-sample replay, status
    /qwen/health, /qwen/v1/models, /qwen/v1/chat/completions
                         -> the project's own Qwen server app, imported unchanged from
                            agentic-pipeline/Qwen3-14B_setup/host.py (create_app + Engine)

The project's agentic_pipeline.ModelClient talks to /qwen/v1 in-process
(httpx.ASGITransport), exactly as it talked to the SSH-tunnelled server before.

Set QWEN_BASE_URL=http://host:port/v1 to use an already running external Qwen
server instead of loading the model inside this process.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = UI_DIR.parent
PIPELINE_DIR = PROJECT_DIR / "agentic-pipeline"
QWEN_SETUP_DIR = PIPELINE_DIR / "Qwen3-14B_setup"
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(QWEN_SETUP_DIR))  # host.py (unmodified)
sys.path.insert(0, str(PIPELINE_DIR))    # agentic_pipeline package (unmodified)

import httpx  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.concurrency import run_in_threadpool  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

import host as qwen_host  # noqa: E402
from agentic_pipeline.client import ModelClient, ModelError  # noqa: E402
from agentic_pipeline.dataset import load_encounters  # noqa: E402
from qwen_engine import ChunkedPrefillEngine  # noqa: E402
from samples import Samples  # noqa: E402
from sessions import FIRST_QUESTION, QUEUE, Session, SessionStore, sse  # noqa: E402

LOG = logging.getLogger("tokenizers_ui")
FRONTEND = UI_DIR / "frontend"
DATASET_DIR = PROJECT_DIR / "aci-bench-corpus"
OUTPUT_DIR = PROJECT_DIR / "agentic-pipeline-output" / "soap_notes"
EXTERNAL_URL = os.getenv("QWEN_BASE_URL", "").strip()
MODEL_NAME = os.getenv("QWEN_MODEL", os.getenv("SERVED_MODEL_NAME", "Qwen3-14B"))
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

store = SessionStore()
samples = Samples(OUTPUT_DIR, DATASET_DIR)
model = {"status": "idle", "message": "", "since": time.time(), "info": None}

# The project's Qwen app; its own lifespan is not used because we load the
# Engine ourselves in the background (so the UI is usable while weights load).
qwen_settings = qwen_host.Settings.from_env()
qwen_app = qwen_host.create_app(qwen_settings, engine_factory=lambda s: None)


def set_model(status: str, message: str, info=None):
    model.update(status=status, message=message, since=time.time(), info=info)
    LOG.info("model %s: %s", status, message)


def load_qwen():
    """Load Qwen3-14B with the project's host.Engine (FP16, 4 GPUs, OOM-guarded)."""
    model_dir = qwen_settings.model_dir
    if not (model_dir / "model.safetensors.index.json").is_file():
        set_model("missing", f"Qwen weights not found at {model_dir}. Run "
                             "bash /scratch/jyothika.goparaju/temp/setup_qwen_and_deps.sh first. "
                             "Saved-sample replay still works.")
        return
    try:
        set_model("loading", f"Checking 4 GPUs and loading FP16 weights from {model_dir} "
                             f"(≤{qwen_settings.weight_memory_gib} GiB per GPU)… this takes a few minutes.")
        # host.Engine (GPU checks, FP16 4-GPU load, warm-up) with memory-bounded chunked prefill.
        engine = ChunkedPrefillEngine(qwen_settings)
        qwen_app.state.engine = engine
        qwen_app.state.generation_lock = asyncio.Lock()
        set_model("ready", f"{qwen_settings.served_name} ready on {len(engine.gpus)} GPUs (FP16).",
                  {"device_map_gpus": sorted(set(engine.device_map.values())), "gpus": engine.gpus})
    except Exception as exc:  # shown in the UI status pill
        LOG.exception("Qwen load failed")
        set_model("error", f"{type(exc).__name__}: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if EXTERNAL_URL:
        app.state.client = ModelClient(EXTERNAL_URL, MODEL_NAME, os.getenv("QWEN_API_KEY", "local-unused"),
                                       timeout=float(os.getenv("REQUEST_TIMEOUT", "900")))
        set_model("connecting", f"Using external Qwen server at {EXTERNAL_URL}")
        app.state.loader = asyncio.create_task(watch_external(app))
    else:
        app.state.client = ModelClient("http://tokenizers-ui.local/qwen/v1", qwen_settings.served_name,
                                       qwen_settings.api_key, timeout=float(os.getenv("REQUEST_TIMEOUT", "900")),
                                       transport=httpx.ASGITransport(app=app))
        if os.getenv("LOAD_MODEL", "1") == "0":
            set_model("disabled", "Model loading disabled (LOAD_MODEL=0): saved-sample replay only.")
        else:
            app.state.loader = asyncio.create_task(asyncio.to_thread(load_qwen))
    yield
    await app.state.client.close()


async def watch_external(app):
    while True:
        try:
            info = await app.state.client.check()
            if model["status"] != "ready":
                set_model("ready", f"{MODEL_NAME} ready at {EXTERNAL_URL}", info)
        except ModelError as exc:
            set_model("connecting", str(exc))
        await asyncio.sleep(20)


app = FastAPI(title="Tokenizers — agentic clinical intake demo", lifespan=lifespan)
app.mount("/qwen", qwen_app)


# ----------------------------------------------------------------- UI API
class NewSession(BaseModel):
    mode: str = Field(default="chat", pattern="^(chat|simulate)$")
    max_turns: int = Field(default=15, ge=1, le=30)
    encounter_id: str | None = None


class PatientMessage(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


async def require_model(app_client: ModelClient):
    if model["status"] != "ready":
        raise HTTPException(503, f"Qwen is not ready ({model['status']}). {model['message']}")
    if not EXTERNAL_URL and app_client.output_limit == 2048:
        await app_client.check()  # reads max_output_tokens from /qwen/health, as the CLI does


def gpu_snapshot():
    try:
        import torch
        if not torch.cuda.is_available():
            return []
        out = []
        for index in range(torch.cuda.device_count()):
            free, total = torch.cuda.mem_get_info(index)
            out.append({"index": index, "name": torch.cuda.get_device_name(index),
                        "used_gib": round((total - free) / 1024**3, 2), "total_gib": round(total / 1024**3, 2)})
        return out
    except Exception:
        return []


@app.get("/api/status")
async def status():
    return {"model": qwen_settings.served_name if not EXTERNAL_URL else MODEL_NAME,
            "status": model["status"], "message": model["message"], "external": bool(EXTERNAL_URL),
            "context_tokens": qwen_settings.context_tokens, "queue": QUEUE.snapshot(),
            "gpus": await run_in_threadpool(gpu_snapshot)}


@app.get("/api/samples")
async def list_samples():
    return await run_in_threadpool(samples.list)


@app.get("/api/samples/{encounter_id}")
async def sample(encounter_id: str):
    try:
        return await run_in_threadpool(samples.events, encounter_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/session")
async def new_session(body: NewSession):
    await require_model(app.state.client)
    encounter = None
    if body.mode == "simulate":
        split = samples.splits().get(body.encounter_id or "")
        if not split:
            raise HTTPException(404, "Pick an ACI-Bench encounter id such as D2N001.")
        encounter = load_encounters(DATASET_DIR, split, body.encounter_id, 1)[0]
    session = store.add(Session(body.mode, app.state.client, max_turns=body.max_turns, encounter=encounter))
    return {"session_id": session.id, "first_question": FIRST_QUESTION, "max_turns": session.max_turns,
            "encounter_id": body.encounter_id if encounter else None}


def get_session(session_id: str) -> Session:
    try:
        return store.get(session_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/session/{session_id}/message")
async def patient_message(session_id: str, body: PatientMessage):
    await require_model(app.state.client)
    session = get_session(session_id)
    if session.mode != "chat":
        raise HTTPException(400, "This session is a patient-agent simulation.")
    return StreamingResponse(sse(session, lambda emit: session.chat_step(emit, body.text.strip())),
                             media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/api/session/{session_id}/finish")
async def finish(session_id: str):
    await require_model(app.state.client)
    session = get_session(session_id)
    return StreamingResponse(sse(session, lambda emit: session.finalize(emit)),
                             media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/api/session/{session_id}/simulate")
async def simulate(session_id: str):
    await require_model(app.state.client)
    session = get_session(session_id)
    if session.mode != "simulate":
        raise HTTPException(400, "Not a simulation session.")
    return StreamingResponse(sse(session, session.simulate), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/api/session/{session_id}/stop")
async def stop(session_id: str):
    get_session(session_id).stop_requested = True
    return {"ok": True}


# --------------------------------------------------------------- frontend
@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(FRONTEND / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/{name}", include_in_schema=False)
async def frontend_file(name: str):
    path = (FRONTEND / name).resolve()
    if path.parent != FRONTEND.resolve() or not path.is_file():
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return FileResponse(path)


def main():
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "7860")), workers=1,
                timeout_keep_alive=75)


if __name__ == "__main__":
    main()
