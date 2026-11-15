"""Four-GPU Qwen3-14B server: a small, non-streaming chat-completions API."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import gc
import hmac
import json
import logging
import os
from pathlib import Path
import time
from typing import Callable, Literal
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

LOG = logging.getLogger("qwen_server")
ROOT = Path(__file__).resolve().parent
MODEL_ID = "Qwen/Qwen3-14B"


@dataclass(frozen=True)
class Settings:
    model_dir: Path = ROOT / "models" / "Qwen3-14B"
    served_name: str = "Qwen3-14B"
    context_tokens: int = 8192
    output_tokens: int = 2048
    weight_memory_gib: float = 8.0
    api_key: str = ""

    @classmethod
    def from_env(cls) -> Settings:
        settings = cls(
            model_dir=Path(os.getenv("MODEL_DIR", str(ROOT / "models/Qwen3-14B"))).resolve(),
            served_name=os.getenv("SERVED_MODEL_NAME", "Qwen3-14B"),
            context_tokens=int(os.getenv("MAX_CONTEXT_TOKENS", "8192")),
            output_tokens=int(os.getenv("MAX_OUTPUT_TOKENS", "2048")),
            weight_memory_gib=float(os.getenv("GPU_WEIGHT_MEMORY_GIB", "8")),
            api_key=os.getenv("MODEL_API_KEY", ""),
        )
        if not (1 <= settings.output_tokens < settings.context_tokens <= 32768):
            raise ValueError("Require 1 <= MAX_OUTPUT_TOKENS < MAX_CONTEXT_TOKENS <= 32768.")
        if settings.weight_memory_gib <= 0:
            raise ValueError("GPU_WEIGHT_MEMORY_GIB must be positive.")
        return settings


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=200_000)


class ResponseFormat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["text", "json_object"] = "text"


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    model: str
    messages: list[Message] = Field(min_length=1, max_length=200)
    max_tokens: int = Field(default=1024, ge=1, le=32768)
    temperature: float = Field(default=0.7, ge=0, le=2)
    top_p: float = Field(default=0.8, gt=0, le=1)
    seed: int | None = Field(default=None, ge=0, le=4_294_967_295)
    stream: Literal[False] = False
    n: Literal[1] = 1
    response_format: ResponseFormat | None = None


def check_gpus(settings: Settings) -> list[dict]:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable. Check your GPU allocation and CUDA PyTorch installation.")
    if torch.cuda.device_count() != 4:
        raise RuntimeError(
            f"Expected exactly four visible GPUs, found {torch.cuda.device_count()}. "
            "Check CUDA_VISIBLE_DEVICES and the cluster allocation."
        )
    architectures = torch.cuda.get_arch_list()
    result = []
    for index in range(4):
        capability = torch.cuda.get_device_capability(index)
        if capability < (7, 5):
            raise RuntimeError(f"GPU {index} has unsupported compute capability {capability}.")
        if capability == (7, 5) and "sm_75" not in architectures:
            raise RuntimeError("This PyTorch wheel lacks sm_75. Install the pinned CUDA 12.6 requirements.")
        free, total = torch.cuda.mem_get_info(index)
        required = int((settings.weight_memory_gib + 1) * 1024**3)
        if free < required:
            raise RuntimeError(
                f"GPU {index} has only {free / 1024**3:.2f} GiB free; "
                f"need at least {required / 1024**3:.2f} GiB for the configured weight budget and headroom."
            )
        # Exercise each GPU before spending time downloading/loading the model.
        with torch.cuda.device(index):
            probe = torch.ones((8, 8), dtype=torch.float16, device=f"cuda:{index}")
            _ = (probe @ probe).sum().item()
            del probe
        result.append({
            "index": index, "name": torch.cuda.get_device_name(index),
            "compute_capability": list(capability),
            "free_gib": round(free / 1024**3, 2), "total_gib": round(total / 1024**3, 2),
        })
    LOG.info("PyTorch %s; bundled CUDA %s; GPUs: %s", torch.__version__, torch.version.cuda, result)
    return result


def download_model(settings: Settings) -> None:
    from huggingface_hub import HfApi, snapshot_download

    settings.model_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = settings.model_dir / "download_manifest.json"
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    requested = os.getenv("MODEL_REVISION")
    # Reuse the first download's exact commit unless the user requests another revision.
    if previous and requested is None:
        revision = previous["resolved_revision"]
    else:
        revision = HfApi().model_info(MODEL_ID, revision=requested or "main").sha
    LOG.info("Downloading %s at revision %s into %s", MODEL_ID, revision, settings.model_dir)
    snapshot_download(
        repo_id=MODEL_ID, revision=revision, local_dir=settings.model_dir,
        allow_patterns=["*.json", "*.safetensors", "*.jinja", "tokenizer*", "vocab*", "merges*"],
        max_workers=4,
    )
    # Check every shard named by the downloaded index, not just config.json.
    index = json.loads((settings.model_dir / "model.safetensors.index.json").read_text())
    missing = [name for name in set(index["weight_map"].values()) if not (settings.model_dir / name).is_file()]
    if missing:
        raise RuntimeError(f"Model download is incomplete; missing shards: {missing}")
    manifest = {
        "model_id": MODEL_ID, "resolved_revision": revision,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    LOG.info("Download complete. Revision recorded in %s", manifest_path)


class Engine:
    def __init__(self, settings: Settings):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.settings = settings
        self.gpus = check_gpus(settings)
        if not (settings.model_dir / "model.safetensors.index.json").is_file():
            raise RuntimeError("Local model not found. Run bash run.sh or bash run.sh --setup-only first.")
        self.tokenizer = AutoTokenizer.from_pretrained(
            settings.model_dir, local_files_only=True, trust_remote_code=False,
        )
        # FP16 is supported on the RTX 2080 Ti. Do not use the checkpoint's BF16 default.
        self.model = AutoModelForCausalLM.from_pretrained(
            settings.model_dir, torch_dtype=torch.float16,
            device_map="balanced",
            max_memory={**{i: f"{settings.weight_memory_gib}GiB" for i in range(4)}, "cpu": "0GiB"},
            attn_implementation="sdpa", low_cpu_mem_usage=True,
            local_files_only=True, trust_remote_code=False, use_safetensors=True,
        ).eval()
        self.device_map = {key: str(value) for key, value in self.model.hf_device_map.items()}
        used = set(self.device_map.values())
        normalized = {value.removeprefix("cuda:") for value in used}
        if normalized != {"0", "1", "2", "3"}:
            raise RuntimeError(f"Expected weights on all four GPUs without CPU/disk offload; got {used}.")
        self.input_device = self.model.get_input_embeddings().weight.device
        LOG.info("Loaded FP16 weights across all four GPUs: %s", self.device_map)
        # A real forward/generation pass catches unsupported kernels before declaring readiness.
        self.complete(ChatRequest(
            model=settings.served_name,
            messages=[Message(role="user", content="Reply with the single word READY.")],
            max_tokens=8, temperature=0,
        ))
        LOG.info("Warmup completed. Endpoint ready.")

    def complete(self, request: ChatRequest) -> dict:
        import torch
        from transformers import set_seed

        messages = [message.model_dump() for message in request.messages]
        json_mode = request.response_format is not None and request.response_format.type == "json_object"
        if json_mode:
            instruction = "Return exactly one valid JSON object. Do not use Markdown fences or text outside the object."
            if messages[0]["role"] == "system":
                messages[0]["content"] += "\n\n" + instruction
            else:
                messages.insert(0, {"role": "system", "content": instruction})
        text = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False,
        )
        inputs = self.tokenizer(text, return_tensors="pt", add_special_tokens=False)
        prompt_tokens = inputs["input_ids"].shape[-1]
        if prompt_tokens + request.max_tokens > self.settings.context_tokens:
            raise HTTPException(400, detail=(
                f"Prompt has {prompt_tokens} tokens; with max_tokens={request.max_tokens} "
                f"it exceeds the {self.settings.context_tokens}-token context limit. "
                "Shorten the history or reduce max_tokens. Nothing was silently truncated."
            ))
        if request.seed is not None:
            set_seed(request.seed)
        inputs = inputs.to(self.input_device)
        sample = request.temperature > 0
        with torch.inference_mode():
            outputs = self.model.generate(
                **inputs, max_new_tokens=request.max_tokens, do_sample=sample,
                temperature=request.temperature if sample else 1.0,
                top_p=request.top_p if sample else 1.0, top_k=20 if sample else 50,
                repetition_penalty=1.0,
                pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id,
                use_cache=True,
            )
        generated = outputs[0, prompt_tokens:].tolist()
        content = self.tokenizer.decode(generated, skip_special_tokens=True).strip()
        if not content:
            raise HTTPException(502, "The model returned empty text. Retry the request.")
        if json_mode:
            try:
                parsed = json.loads(content)
                if not isinstance(parsed, dict):
                    raise ValueError("Expected an object.")
            except (json.JSONDecodeError, ValueError) as exc:
                raise HTTPException(502, "Model did not return a valid JSON object. Retry, simplify the prompt, or increase max_tokens.") from exc
        eos = self.model.generation_config.eos_token_id
        eos = {eos} if isinstance(eos, int) else set(eos or [])
        finish_reason = "stop" if generated and generated[-1] in eos else "length"
        return {
            "id": "chatcmpl-" + uuid.uuid4().hex,
            "object": "chat.completion", "created": int(time.time()),
            "model": self.settings.served_name,
            "choices": [{
                "index": 0, "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }],
            "usage": {
                "prompt_tokens": prompt_tokens, "completion_tokens": len(generated),
                "total_tokens": prompt_tokens + len(generated),
            },
        }


def create_app(settings: Settings | None = None, engine_factory: Callable = Engine) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.engine = await run_in_threadpool(engine_factory, settings)
        app.state.generation_lock = asyncio.Lock()
        yield

    app = FastAPI(title="Qwen3-14B four-GPU endpoint", lifespan=lifespan)

    async def authorize(authorization: str | None = Header(default=None)):
        if settings.api_key and not hmac.compare_digest(authorization or "", "Bearer " + settings.api_key):
            raise HTTPException(401, "Invalid or missing bearer token.")

    @app.get("/health")
    async def health():
        return {
            "status": "ready", "model": settings.served_name, "dtype": "float16",
            "context_tokens": settings.context_tokens, "max_output_tokens": settings.output_tokens,
            "gpu_count": len(app.state.engine.gpus), "device_map": app.state.engine.device_map,
        }

    @app.get("/v1/models", dependencies=[Depends(authorize)])
    async def models():
        return {"object": "list", "data": [{
            "id": settings.served_name, "object": "model", "created": 0, "owned_by": "local",
        }]}

    @app.post("/v1/chat/completions", dependencies=[Depends(authorize)])
    async def chat(request: ChatRequest):
        if request.model not in {settings.served_name, MODEL_ID}:
            raise HTTPException(404, f"Unknown model. Use {settings.served_name}.")
        if request.max_tokens > settings.output_tokens:
            raise HTTPException(400, f"max_tokens must be <= {settings.output_tokens}.")
        if request.messages[-1].role != "user":
            raise HTTPException(400, "The last message must have role 'user'.")
        async with app.state.generation_lock:
            try:
                return await run_in_threadpool(app.state.engine.complete, request)
            except HTTPException:
                raise
            except Exception as exc:
                import torch

                LOG.exception("Generation failed")
                if isinstance(exc, torch.cuda.OutOfMemoryError):
                    gc.collect()
                    for index in range(4):
                        with torch.cuda.device(index):
                            torch.cuda.empty_cache()
                    raise HTTPException(503, "GPU out of memory. Shorten the prompt or reduce max_tokens.") from exc
                raise HTTPException(500, "Generation failed; inspect the server terminal.") from exc

    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check-gpus", action="store_true")
    group.add_argument("--download-only", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.check_gpus:
        print(json.dumps(check_gpus(settings), indent=2))
    elif args.download_only:
        download_model(settings)
    else:
        import uvicorn

        uvicorn.run(create_app(settings), host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")), workers=1)


if __name__ == "__main__":
    main()
