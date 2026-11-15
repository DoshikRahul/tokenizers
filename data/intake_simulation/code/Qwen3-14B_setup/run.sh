#!/usr/bin/env bash
# Run with bash run.sh; no root access or existing environment is required.
set -Eeuo pipefail
trap 'echo "Setup stopped at line $LINENO. Fix the error above and rerun bash run.sh." >&2' ERR

SETUP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SETUP_DIR"

case "${1:-}" in
  "") MODE=all ;;
  --setup-only) MODE=setup ;;
  --serve-only) MODE=serve ;;
  --check-only) MODE=check ;;
  -h|--help)
    cat <<'HELP'
Usage: bash run.sh [--setup-only | --serve-only | --check-only]
  no argument    Create venv, install requirements, check GPUs, download, serve.
  --setup-only   Install/check/download, then exit without loading the model.
  --serve-only   Start from the existing environment and local model; no download.
  --check-only   Check GPUs using the existing environment; no download or server.

Optional environment variables:
  PYTHON_BIN=python3.11    Python 3.10, 3.11, or 3.12 for environment creation.
  CUDA_VISIBLE_DEVICES=0,1,2,3  Exactly four allocated GPUs; existing value respected.
  PORT=8000               Endpoint port. HOST defaults to 127.0.0.1.
  MODEL_REVISION=main     Hugging Face revision on initial download.
  MAX_CONTEXT_TOKENS=8192 MAX_OUTPUT_TOKENS=2048 GPU_WEIGHT_MEMORY_GIB=8
  MODEL_API_KEY=...       Optional bearer token for API requests.
HELP
    exit 0 ;;
  *) echo "Unknown argument: $1. Use --help." >&2; exit 2 ;;
esac
if (( $# > 1 )); then
  echo "Use at most one mode flag. See --help." >&2
  exit 2
fi

# Keep caches and downloaded files in scratch, beside the script.
export HF_HOME="${HF_HOME:-$SETUP_DIR/.cache/huggingface}"
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$SETUP_DIR/.cache/pip}"
export MODEL_DIR="${MODEL_DIR:-$SETUP_DIR/models/Qwen3-14B}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0,1,2,3}"
export TOKENIZERS_PARALLELISM=false
export HF_HUB_DISABLE_TELEMETRY=1
# Use the standard HTTP downloader for a predictable initial setup.
export HF_HUB_DISABLE_XET=1
export PYTHONUNBUFFERED=1

if [[ "$MODE" == all || "$MODE" == setup ]]; then
  if [[ ! -x "$SETUP_DIR/.venv/bin/python" ]]; then
    if [[ -n "${PYTHON_BIN:-}" ]]; then
      SELECTED_PYTHON="$PYTHON_BIN"
    else
      SELECTED_PYTHON=""
      for candidate in python3.12 python3.11 python3.10 python3; do
        if command -v "$candidate" >/dev/null 2>&1 &&
          "$candidate" -c 'import sys; sys.exit(not ((3, 10) <= sys.version_info[:2] <= (3, 12)))'; then
          SELECTED_PYTHON="$candidate"
          break
        fi
      done
    fi
    if [[ -z "$SELECTED_PYTHON" ]]; then
      echo "Python 3.10-3.12 is required. Load a cluster Python module, then rerun." >&2
      exit 1
    fi
    "$SELECTED_PYTHON" -c 'import sys; assert (3, 10) <= sys.version_info[:2] <= (3, 12), "Use Python 3.10-3.12"'
    echo "[1/5] Creating .venv using $SELECTED_PYTHON"
    "$SELECTED_PYTHON" -m venv "$SETUP_DIR/.venv"
  else
    echo "[1/5] Reusing this folder's .venv"
  fi
fi

PYTHON="$SETUP_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "No environment found. Run bash run.sh first." >&2
  exit 1
fi

if [[ "$MODE" == all || "$MODE" == setup ]]; then
  echo "[2/5] Installing pinned requirements (first run downloads CUDA libraries)"
  "$PYTHON" -m pip install --upgrade 'pip==25.1.1'
  "$PYTHON" -m pip install -r "$SETUP_DIR/req.txt"
  "$PYTHON" -m pip check
  "$PYTHON" -m pip freeze > "$SETUP_DIR/installed_versions.txt"
fi

echo "[3/5] Checking the four GPUs and the PyTorch CUDA build"
"$PYTHON" "$SETUP_DIR/host.py" --check-gpus
if [[ "$MODE" == check ]]; then exit 0; fi

if [[ "$MODE" == all || "$MODE" == setup ]]; then
  echo "[4/5] Downloading/resuming Qwen/Qwen3-14B (approximately 30 GB)"
  "$PYTHON" "$SETUP_DIR/host.py" --download-only
else
  echo "[4/5] Using the existing local model; no download"
fi
if [[ "$MODE" == setup ]]; then
  echo "Setup complete. Start the endpoint with: bash run.sh --serve-only"
  exit 0
fi

echo "[5/5] Starting endpoint; loading weights and warming up may take several minutes"
exec "$PYTHON" "$SETUP_DIR/host.py"
