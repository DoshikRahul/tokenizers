"""Configuration for the integrated Stage 2-3 controller and the evaluation.

Environment variables override these defaults. All models are used for inference only.
"""
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent

# ---- inputs / outputs -------------------------------------------------------
STAGE1_OUTPUT_JSON = Path(os.environ.get(
    "STAGE1_OUTPUT_JSON",
    PROJECT_DIR.parent / "stage1_pipeline" / "stage1_colab_project" / "stage1" / "stage1_output.json",
))
OUTPUT_DIR = Path(os.environ.get("RQ1_OUTPUT_DIR", PROJECT_DIR / "output"))
CASES_DIR = OUTPUT_DIR / "cases"                  # one checkpoint JSON per case
STAGE23_JSON = OUTPUT_DIR / "stage23_output.json"
UNSUPPORTED_DIR = OUTPUT_DIR / "unsupported_claims"   # one file per case: claims kept OUT of the note
FINAL_NOTES_DIR = OUTPUT_DIR / "final_notes"          # readable note: improved S/O + original, untouched A/P
EVAL_DIR = OUTPUT_DIR / "evaluation"

# ---- LLM (inference only) ---------------------------------------------------
# "openai" = OpenAI-compatible server (e.g. a llama.cpp GPU box); "ollama" = local Ollama.
# The API key comes from the environment only and is never written to a file.
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")          # e.g. http://10.2.236.141:8080/v1
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "llama3")
LLM_BACKEND = os.environ.get("LLM_BACKEND", "openai" if LLM_BASE_URL else "ollama")
LLM_JSON_MODE = os.environ.get("LLM_JSON_MODE", "0") == "1"   # send response_format=json_object if supported

OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3:8b")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "900"))
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))

# ---- encoder / LM models (inference only) ----------------------------------
# NLI backend: "remote" = DeBERTa NLI API on a GPU host (POST /nli, X-API-Key header); "local" = load on this PC.
# The key comes from the environment only and is never written to a file.
NLI_BASE_URL = os.environ.get("NLI_BASE_URL", "")          # e.g. http://10.2.236.141:8081
NLI_API_KEY = os.environ.get("NLI_API_KEY", "")
NLI_BACKEND = os.environ.get("NLI_BACKEND", "remote" if NLI_BASE_URL else "local")
NLI_MAX_WORDS = int(os.environ.get("NLI_MAX_WORDS", "220"))   # premise chunk size for the remote scorer
NLI_MODEL = os.environ.get("NLI_MODEL", "MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "all-MiniLM-L6-v2")
# Embedding backend: "remote" = MiniLM served on a GPU host (/v1/embeddings, no key); "local" = load on this PC.
EMBED_BASE_URL = os.environ.get("EMBED_BASE_URL", "")      # e.g. http://10.2.236.141:8082
EMBED_BACKEND = os.environ.get("EMBED_BACKEND", "remote" if EMBED_BASE_URL else "local")
PPL_MODEL = os.environ.get("PPL_MODEL", "gpt2")

# ---- Stage 2 thresholds (tune on the dev split, then freeze) ---------------
TE = float(os.environ.get("TE", "0.90"))             # entailment >= TE      -> supported
TA = float(os.environ.get("TA", "0.50"))             # TA <= entail < TE     -> uncertain (kept, flagged)
TCONTRA = float(os.environ.get("TCONTRA", "0.50"))   # contradiction >= TCONTRA (and entail < TE) -> contradicted
# Claims whose entailment is below TA and are not contradicted are taken out of the note and saved to
# UNSUPPORTED_DIR (not deleted, and not asserted to be false). Set "flag" to keep them in the note instead.
UNSUPPORTED_POLICY = os.environ.get("UNSUPPORTED_POLICY", "remove")
CORRECT_CONTRADICTIONS = os.environ.get("CORRECT_CONTRADICTIONS", "1") == "1"

# ---- Stage 3 thresholds (tune on the dev split, then freeze) ---------------
# Whose statements can become additions. Patient only by default: S/O facts are patient-reported, and doctor
# declaratives are mostly plans or hypotheticals (set CANDIDATE_SPEAKERS="Patient,Doctor" to include them).
CANDIDATE_SPEAKERS = tuple(s.strip() for s in os.environ.get("CANDIDATE_SPEAKERS", "Patient").split(","))
COV_MIN = float(os.environ.get("COV_MIN", "0.40"))           # coverage <= COV_MIN -> candidate omission
MAX_CANDIDATES = int(os.environ.get("MAX_CANDIDATES", "25")) # lowest-coverage candidates validated per case
ADD_ENTAIL_MIN = float(os.environ.get("ADD_ENTAIL_MIN", "0.80"))   # statement must be entailed by the dialogue
ADD_CONTRA_MAX = float(os.environ.get("ADD_CONTRA_MAX", "0.30"))
DUP_ENTAIL_MIN = float(os.environ.get("DUP_ENTAIL_MIN", "0.70"))   # entailed by current S/O -> duplicate
DUP_SIM_MIN = float(os.environ.get("DUP_SIM_MIN", "0.85"))         # near-identical sentence in S/O -> duplicate
MAX_QUESTIONS = int(os.environ.get("MAX_QUESTIONS", "5"))

# ---- Evaluation -------------------------------------------------------------
FACT_REPRESENTED_MIN = float(os.environ.get("FACT_REPRESENTED_MIN", "0.50"))  # reference fact entailed by output
FACT_SUPPORTED_MIN = float(os.environ.get("FACT_SUPPORTED_MIN", "0.80"))      # reference fact entailed by dialogue
ANNOTATION_SAMPLE_SIZE = int(os.environ.get("ANNOTATION_SAMPLE_SIZE", "100"))
RANDOM_SEED = int(os.environ.get("RANDOM_SEED", "42"))
