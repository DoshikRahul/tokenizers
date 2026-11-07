"""RQ2 configuration. Every value can be overridden with an environment variable of the same name.

Follows the conventions of verify_and_ask_pipeline/Stage23_pipeline/code/config.py so the same
LLM / NLI servers can be reused.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent


def _env(name, default):
    return os.environ.get(name, default)


# ---------------------------------------------------------------- paths
ACI_DIR = Path(_env("ACI_DIR", REPO / "aci-bench-corpus" / "challenge_data"))
AGENTIC_OUT = Path(_env("AGENTIC_OUT", REPO / "agentic-pipeline-output" / "soap_notes"))
DATA_DIR = Path(_env("RQ2_DATA_DIR", ROOT / "data_out"))          # built datasets
RUNS_DIR = Path(_env("RQ2_RUNS_DIR", ROOT / "runs"))              # per-condition predictions (resumable)
REPORT_DIR = Path(_env("RQ2_REPORT_DIR", ROOT / "reports"))
REF_DIR = Path(_env("RQ2_REF_DIR", ROOT / "reference_corpus"))    # MedlinePlus chunks + indexes

# ACI-Bench split files. dev = valid (threshold / k tuning), test = test1 (proposal E1/E2).
ACI_SPLITS = {
    "train": "train.csv",
    "dev": "valid.csv",
    "test1": "clinicalnlp_taskB_test1.csv",
    "test2": "clinicalnlp_taskC_test2.csv",
    "test3": "clef_taskC_test3.csv",
}

# ---------------------------------------------------------------- generator LLM
# Used for: planting errors, feature extraction, feature->statement linking.
# NOT used as the verifier. Default = the team's OpenAI-compatible server (Qwen3-14B host.py,
# OpenRouter Qwen2.5-7B, llama.cpp, vLLM ...). "ollama" is supported as in Stage23.
GEN_BASE_URL = _env("GEN_BASE_URL", _env("LLM_BASE_URL", ""))
GEN_API_KEY = _env("GEN_API_KEY", _env("LLM_API_KEY", ""))
GEN_MODEL = _env("GEN_MODEL", _env("LLM_MODEL", "Qwen3-14B"))
GEN_BACKEND = _env("GEN_BACKEND", "openai" if GEN_BASE_URL else "ollama")
OLLAMA_BASE = _env("OLLAMA_BASE", "http://127.0.0.1:11434")
OLLAMA_MODEL = _env("OLLAMA_MODEL", "llama3:8b")
GEN_TIMEOUT = int(_env("GEN_TIMEOUT", "600"))
GEN_JSON_MODE = _env("GEN_JSON_MODE", "0") == "1"
# Qwen3 models think by default; "/no_think" in the system prompt switches it off.
GEN_NO_THINK = _env("GEN_NO_THINK", "1") == "1"

# ---------------------------------------------------------------- verifier (U2, U3, U4, S1)
# "hf"     : load base model (+ optional QLoRA adapter) locally; exact label probabilities.
# "openai" : OpenAI-compatible server; label probabilities from logprobs when the server returns
#            them, otherwise a hard label (prob 0/1) -> threshold sweeps degrade to one point.
# "stub"   : deterministic heuristic for smoke tests only.
VERIFIER_BACKEND = _env("VERIFIER_BACKEND", "hf")
VERIFIER_BASE_MODEL = _env("VERIFIER_BASE_MODEL", "Qwen/Qwen2.5-3B-Instruct")
VERIFIER_ADAPTER = _env("VERIFIER_ADAPTER", "")          # path to QLoRA adapter dir ("" = base model)
VERIFIER_4BIT = _env("VERIFIER_4BIT", "1") == "1"
VERIFIER_MAX_INPUT_TOKENS = int(_env("VERIFIER_MAX_INPUT_TOKENS", "6144"))
VERIFIER_BASE_URL = _env("VERIFIER_BASE_URL", "")
VERIFIER_API_KEY = _env("VERIFIER_API_KEY", "")
VERIFIER_MODEL = _env("VERIFIER_MODEL", "qwen/qwen-2.5-7b-instruct")
VERIFIER_NAME = _env("VERIFIER_NAME", "")               # tag used in run directory names

# Label strings. MUST match the targets used when the QLoRA verifier was trained.
LABELS_ENTAIL = ("supported", "contradicted", "unsupported")      # S/O-style uniform entailment
LABELS_CHAIN = ("chain_ok", "chain_broken")                       # A/P evidence chain

# ---------------------------------------------------------------- DeBERTa (U1)
NLI_MODEL = _env("NLI_MODEL", "MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli")
NLI_BASE_URL = _env("NLI_BASE_URL", "")
NLI_API_KEY = _env("NLI_API_KEY", "")
# uMedSum (Nagar et al., 2025, App. A.7) thresholds, as in Baseline_Implementation stage_2
UMEDSUM_TE = float(_env("UMEDSUM_TE", "0.9"))   # E > Te          -> faithful
UMEDSUM_TC = float(_env("UMEDSUM_TC", "0.8"))   # N + C > Tc      -> confabulated
UMEDSUM_TA = float(_env("UMEDSUM_TA", "0.5"))   # atom E > Ta     -> keep atom
UMEDSUM_MAX_DEPTH = int(_env("UMEDSUM_MAX_DEPTH", "2"))

# ---------------------------------------------------------------- decision thresholds
# Tuned on dev (evaluate_rq2.py --tune), then frozen for test. A statement is REJECTED (flag or
# delete, scored the same way for every condition) when P(reject) >= threshold.
TAU_ENTAIL = float(_env("TAU_ENTAIL", "0.5"))   # U2: reject if P(supported) < TAU_ENTAIL
TAU_CHAIN = float(_env("TAU_CHAIN", "0.5"))     # U3/U4: reject if P(chain_broken) >= TAU_CHAIN

# ---------------------------------------------------------------- retrieval
EMBED_MODEL = _env("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
RRF_K = int(_env("RRF_K", "60"))                 # Cormack et al. 2009 constant
REF_TOP_K = int(_env("REF_TOP_K", "3"))          # tuned over {1,3,5} on dev
TURN_TOP_K = int(_env("TURN_TOP_K", "5"))        # S2, tuned over {1,3,5} on dev
# A retrieved passage counts as "found" only if its dense cosine to the query is at least this;
# below it U4 behaves exactly like U3 for that statement (reported as reference coverage).
REF_MIN_COS = float(_env("REF_MIN_COS", "0.35"))
MEDLINEPLUS_XML_URL = _env("MEDLINEPLUS_XML_URL", "")  # set to the current mplus_topics_YYYY-MM-DD.xml URL

# ---------------------------------------------------------------- evidence chain
MAX_LINKED_FEATURES = int(_env("MAX_LINKED_FEATURES", "8"))
FEATURE_GROUNDING = _env("FEATURE_GROUNDING", "verifier")   # "verifier" | "nli" | "off"

# ---------------------------------------------------------------- evaluation
SEED = int(_env("SEED", "42"))
N_BOOT = int(_env("N_BOOT", "2000"))
H2_MARGIN = float(_env("H2_MARGIN", "0.05"))     # H2: rejection recall within 5 points of U1/U2
