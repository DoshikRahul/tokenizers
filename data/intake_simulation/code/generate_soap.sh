#!/usr/bin/env bash
# By default, generate notes for all 207 encounters in the five challenge splits.
set -Eeuo pipefail
PIPELINE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PIPELINE_DIR"
if [[ ! -x .venv/bin/python ]]; then
  "${PYTHON_BIN:-python3}" -m venv .venv
fi
source .venv/bin/activate
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$PIPELINE_DIR/.venv/.pip-cache}"
REQUIREMENTS_HASH="$(sha256sum req.txt | cut -d ' ' -f 1)"
if [[ ! -f .venv/requirements.sha256 ]] || [[ "$(cat .venv/requirements.sha256)" != "$REQUIREMENTS_HASH" ]]; then
  .venv/bin/python -m pip install --timeout 120 -r req.txt
  .venv/bin/python -m pip check
  printf '%s\n' "$REQUIREMENTS_HASH" > .venv/requirements.sha256
fi
exec .venv/bin/python -m agentic_pipeline.cli --split all --limit 0 "$@"
