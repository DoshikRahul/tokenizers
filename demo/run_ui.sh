#!/usr/bin/env bash
# Start the Tokenizers expo demo: UI + agentic pipeline API + Qwen3-14B on ONE port.
#   bash demo/run_ui.sh                 # loads Qwen3-14B on the 4 GPUs, serves on :7860
#   PORT=8080 bash demo/run_ui.sh       # another port
#   LOAD_MODEL=0 bash demo/run_ui.sh    # no GPU: only replay of saved project outputs
#   QWEN_BASE_URL=http://127.0.0.1:8001/v1 bash demo/run_ui.sh   # use an external Qwen server
set -Eeuo pipefail
UI_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TEMP_DIR="/scratch/jyothika.goparaju/temp"
VENV="/scratch/jyothika.goparaju/models_env"

export MODEL_DIR="${MODEL_DIR:-$TEMP_DIR/models/Qwen3-14B}"
export HF_HOME="${HF_HOME:-$TEMP_DIR/hf_cache}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0,1,2,3}"
# host.py defaults: 8192-token context, 2048 output tokens, 8 GiB weights per GPU (+ headroom).
export MAX_CONTEXT_TOKENS="${MAX_CONTEXT_TOKENS:-8192}"
export MAX_OUTPUT_TOKENS="${MAX_OUTPUT_TOKENS:-2048}"
export GPU_WEIGHT_MEMORY_GIB="${GPU_WEIGHT_MEMORY_GIB:-8}"
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
export TOKENIZERS_PARALLELISM=false
export LANGSMITH_TRACING=false
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1   # never write __pycache__ into the project's pipeline folders
export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-7860}"

PY="$VENV/bin/python"
if ! "$PY" -c "import langgraph, httpx" 2>/dev/null; then
  echo "Missing pipeline packages in models_env. Run: bash $TEMP_DIR/setup_qwen_and_deps.sh" >&2
  exit 1
fi
if [[ "${LOAD_MODEL:-1}" != 0 && -z "${QWEN_BASE_URL:-}" && ! -f "$MODEL_DIR/model.safetensors.index.json" ]]; then
  echo "WARNING: Qwen weights not found in $MODEL_DIR — only sample replay will work." >&2
  echo "         Run: bash $TEMP_DIR/setup_qwen_and_deps.sh" >&2
fi

echo "Tokenizers demo on http://$(hostname):$PORT  (tunnel: ssh -L $PORT:$(hostname):$PORT ...)"
exec "$PY" "$UI_DIR/backend/server.py"
