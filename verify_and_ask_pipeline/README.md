# RQ1: Verify-Then-Ask for SOAP notes

Improves the **Subjective / Objective (S/O)** sections of SOAP notes generated from doctor-patient
conversations. **Assessment / Plan (A/P) is never changed.** All models are used for inference only (no training).

## Pipeline

| Stage | What it does | Output |
|---|---|---|
| 1. Generate | LLaMA-3-8B writes a SOAP note from the conversation. S/O goes forward, A/P is saved separately. | `stage1_output.json` |
| 2. Verify (confabulation removal) | Each S/O sentence is checked against the conversation with NLI. Unsupported or contradicted claims are corrected or removed and saved separately, never silently deleted. | verified S/O, `unsupported_claims/` |
| 3a. Fill omissions | Patient statements the note misses are rewritten, validated by NLI, de-duplicated and inserted (GPT-2 perplexity for placement). | final S/O |
| 3b. Ask | Unresolved gaps are listed as questions. They never change the S/O. | questions per case |

The final note is the Stage 3 S/O plus the Stage 1 A/P, unchanged. The ground-truth note is never an input to Stages 1-3.

Systems compared in the evaluation: **A** = Stage 1 S/O, **B** = Stage 2 verified S/O, **C** = Stage 3 final S/O.

## Models

| Model | Role | Where it runs |
|---|---|---|
| LLaMA-3-8B-Instruct (Q8, llama.cpp) | generation, rewriting, gaps, fact extraction | GPU server, `:8080` |
| DeBERTa-v3-large NLI | verification and scoring | GPU server, `:8081` (key via `X-API-Key`) |
| all-MiniLM-L6-v2 | coverage and duplicate similarity | GPU server, `:8082` |
| GPT-2 | fluency-based insertion position | local CPU |
| roberta-large | BERTScore | local CPU |

Outputs and scores are always written to this PC. The servers only answer requests.

## Layout

```
run_local.ps1                 entry point for every step
requirements.txt              combined dependencies
stage1_pipeline/stage1_code  Stage 1 (prepare, generate, evaluate)
stage23_pipeline/                 Stage 2-3 controller + evaluation
  output/                     all results (see below)
```

## Setup

Python 3.12 and PowerShell on Windows.

```powershell
cd C:\Users\HP\Downloads\tokenizers\tokenizers
.\run_local.ps1 setup
```

Keys are read from the environment only and are never stored in files:

```powershell
$env:LLM_API_KEY = "<key>"
$env:NLI_API_KEY = "<key>"
$env:PYTHONIOENCODING = "utf-8"
```

Server URLs default to the values at the top of `run_local.ps1`; override them with `LLM_BASE_URL`,
`NLI_BASE_URL` and `EMBED_BASE_URL`. Set `NLI_BASE_URL` / `EMBED_BASE_URL` to an empty string to load
those models locally instead.

## Run

```powershell
.\run_local.ps1 check                                   # servers reachable, context large enough
.\run_local.ps1 prepare                                 # build dataset, seeded dev/test split (22 / 88)
.\run_local.ps1 stage1                                  # Stage 1 + its evaluation

.\run_local.ps1 stage23 --stage2-only --split dev       # Stage 2 only (also --split test)
.\run_local.ps1 stage23 --split dev --reuse-stage2      # Stage 3 on dev
.\run_local.ps1 eval --split dev

.\run_local.ps1 stage23 --split test --reuse-stage2      # final run, thresholds frozen
.\run_local.ps1 eval --split test
```

Every step checkpoints per case. If a run is interrupted or a server goes down, rerun the same command and it
resumes. Use `--retry-errors` to redo cases that failed, and `--overwrite` to recompute.
Useful flags: `--limit N` (smoke test), `--no-ask`, `--no-gpt2`.

## Outputs

Under `rq1_pipeline/output/`:

| Path | Content |
|---|---|
| `final_notes/<case>.md` | improved S/O and the unchanged A/P |
| `cases/`, `stage23_output.json` | per-case Stage 3 results |
| `stage2_only/` | Stage 2 results for all 110 cases |
| `unsupported_claims/` | claims kept out of the note, with reasons |
| `evaluation/results_{dev,test}.md/.json` | scores |
| `evaluation/annotation_*.csv` | samples for human spot-checking |

Stage 1 results are in `stage1_pipeline/stage1/`.

## Evaluation

Three phases: (1) ROUGE-1/2/L/Lsum and BERTScore against the reference S/O (S/O combined and Subjective only);
(2) NLI grounding of each claim against the conversation (supported, unsupported, contradicted rates);
(3) LLM-extracted reference facts, with atomic, critical and recoverable fact recall, gap-detection precision and
recall, unsupported and duplicate addition rates, question redundancy, and `ap_unchanged_rate` (must be 1.0).
