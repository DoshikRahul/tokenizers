# UI — live expo demo (Team Tokenizers)

One page, one port: the frontend, the agentic-pipeline API and Qwen3-14B all run
in a single process.

```text
UI/
├── run_ui.sh            # start everything on one port (default 7860)
├── frontend/
│   ├── index.html       # the demo page (single file)
│   └── logo.jpg
└── backend/
    ├── server.py        # FastAPI: serves the page, /api/*, and mounts host.py's app at /qwen
    ├── sessions.py      # streaming outer loop around agentic_pipeline.Consultation
    └── samples.py       # replays saved runs from agentic-pipeline-output/soap_notes
```

Nothing outside `UI/` is modified. The backend imports, unchanged:
- `agentic-pipeline/agentic_pipeline` (Consultation LangGraph, PatientAgent, ModelClient, schemas, prompts)
- `agentic-pipeline/Qwen3-14B_setup/host.py` (Engine + `/health`, `/v1/models`, `/v1/chat/completions`)

## 1. One-time setup (downloads, run yourself)

```bash
bash /scratch/jyothika.goparaju/temp/setup_qwen_and_deps.sh
```

The setup script does three things:
- Installs the pipeline's missing packages (`langgraph`, `httpx`, …) into `/scratch/jyothika.goparaju/models_env`.
- Checks the 4 GPUs.
- Downloads `Qwen/Qwen3-14B` (~30 GB) to `/scratch/jyothika.goparaju/temp/models/Qwen3-14B`.

## 2. Start the demo (on the GPU node)

```bash
screen -S tokenizers-ui
bash /scratch/jyothika.goparaju/tokenizers/UI/run_ui.sh
# detach: Ctrl+a then d
```

Loading the model takes a few minutes. The status pill in the page header turns green when Qwen is ready.
Qwen3-14B is loaded with the project's `host.py` settings:
- FP16 weights, capped at 8 GiB per RTX 2080 Ti across all 4 GPUs, never offloaded to CPU.
- 8192-token context, one generation at a time.
- Out-of-memory errors are caught, the cache is freed, and the request is retried by the pipeline client.

## 3. Open it from your laptop

```bash
ssh -N -J jyothika.goparaju@ada-gw1.iiit.ac.in -L 7860:127.0.0.1:7860 jyothika.goparaju@gnode087
```

Then browse to <http://localhost:7860>.

## Page tabs

1. **Live consultation.** You are the patient. You describe your issue and the doctor agent asks follow-up questions. After every answer, the orchestrator → specialists → aggregator graph updates the shared record, and the **Subjective / Objective** panel fills in live. Press **Finish** (or let the doctor team decide history is complete) to freeze the evidence and generate Assessment & Plan.
2. **Patient-agent simulation.** The real project setup: the `PatientAgent` answers from an ACI-Bench transcript that the doctor team never sees.
3. **Saved project runs.** Replays the encounters in `agentic-pipeline-output/soap_notes` step by step. It needs no GPU, so it is a safe fallback for the expo:

   ```bash
   LOAD_MODEL=0 bash UI/run_ui.sh
   ```

Each model call takes roughly 5–60 s on 2080 Ti GPUs (a 14B model in plain HF generate), so one live turn takes about 1–2 minutes. The trace panel shows each agent working, with timings.
