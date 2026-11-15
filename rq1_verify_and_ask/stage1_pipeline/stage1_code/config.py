"""Stage 1 configuration. Environment variables override these defaults."""
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
DATASET_ROOT = Path(os.environ.get(
    "DATASET_ROOT",
    PROJECT_DIR / "dataset"
))
OUTPUT_DIR = Path(os.environ.get("STAGE1_OUTPUT_DIR", PROJECT_DIR / "stage1"))
PREPARED_JSON = OUTPUT_DIR / "prepared_dataset.json"
OUTPUT_JSON = OUTPUT_DIR / "stage1_output.json"
GENERATED_DIR = OUTPUT_DIR / "generated_notes"
CASES_DIR = OUTPUT_DIR / "cases"  # one checkpoint JSON per case, used for resume

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3:8b")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "900"))
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))  # prompt + conversation must fit
TEMPERATURE = float(os.environ.get("STAGE1_TEMPERATURE", "0.1"))

# Dev/test split (tune thresholds on dev, freeze, then report on test).
SPLIT_SEED = int(os.environ.get("SPLIT_SEED", "42"))
DEV_FRACTION = float(os.environ.get("DEV_FRACTION", "0.2"))

# LLM backend: "openai" = OpenAI-compatible server (e.g. a llama.cpp GPU box), "ollama" = local Ollama.
# The API key is read from the environment and never stored in a file.
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")          # e.g. http://10.2.236.141:8080/v1
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "llama3")
LLM_BACKEND = os.environ.get("LLM_BACKEND", "openai" if LLM_BASE_URL else "ollama")
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "1500"))
