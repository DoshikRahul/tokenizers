# Clinical SOAP Note Generation, Multi-Agent Intake & Verify-and-Ask Pipeline

## 1. Brief Overview

This repository contains the datasets, baseline implementation, multi-agent clinical consultation simulator, and proposed **Verify-and-Ask** framework for **Team Tokenizers** (*"One Encounter, Two Readers: Verified Clinical Notes for Doctors and Faithful Summaries for Patients"*).

- **Full Technical Report:** See [`PROJECT_REPORT.md`](./PROJECT_REPORT.md) for the complete dataset specifications, system architectures, model hyperparameters, exact prompts, evaluation metrics, experimental results, and future roadmap.
- **Reference Papers:**
  - [`Tokenziers_modified.pdf`](./Tokenziers_modified.pdf) — Team Tokenizers project proposal and experimental design.
  - [`2025.acl-long.134 (1).pdf`](./2025.acl-long.134%20(1).pdf) — *uMedSum: A Unified Framework for Clinical Abstractive Summarization* (Nagar et al., ACL 2025).

---

## 2. Repository Structure

```text
tokenizers/
├── README.md                                   # Repository overview, folder guide, and run commands
├── PROJECT_REPORT.md                           # Detailed technical and experimental report
├── Tokenziers_modified.pdf                     # Project proposal & research design (RQ1 & RQ2)
├── 2025.acl-long.134 (1).pdf                   # uMedSum baseline reference paper (ACL 2025)
│
├── aci-bench-corpus/                           # Raw ACI-Bench dataset (207 clinical encounters)
│   ├── README.txt                              # Dataset documentation and full D2N001 example
│   ├── challenge_data/                         # Main train (67), valid (20), test1/2/3 (40 each) CSVs + metadata
│   └── src_experiment_data/                    # Alternative ASR, ASR-corrected, and human transcripts
│
├── Baseline_Implementation/                    # uMedSum (ACL 2025) full-SOAP baseline reproduction
│   ├── tokenizer's_umedsum_baseline.ipynb      # End-to-end Google Colab notebook for the baseline
│   ├── aci_dataset_rq1_baseline/               # Prepared zero-leakage JSON splits (120, 140, 204 samples) + 3 ICL demos
│   │   ├── prepare_datasets.py                 # Script to build test_only, test+val, and test+val+train splits
│   │   ├── icl_examples.json                   # 3 held-out train demonstrations (D2N002, D2N023, D2N035)
│   │   ├── test_only/                          # 120 test samples (test1 + test2 + test3)
│   │   └── test+val/                           # 140 test + validation samples (used in baseline evaluation)
│   └── umedsum_pipeline_baseline/              # Modular 3-stage uMedSum pipeline + benchmark evaluator
│       ├── run_all_stages.py                   # Master runner (Stage 1 -> Stage 2 -> Stage 3 -> Evaluation)
│       ├── evaluate_metrics.py                 # ROUGE, BERTScore, SummaC-Conv, QuestEval, and DeBERTa Entailment
│       ├── requirements.txt                    # Python dependencies for baseline
│       ├── stage_1/                            # Stage 1: Element-Aware + 1-shot ICL SOAP generation (LLaMA-3-8B)
│       ├── stage_2/                            # Stage 2: RTB-TS confabulation removal (DeBERTa-v3-large NLI)
│       ├── stage_3/                            # Stage 3: MMR missing info detection (MiniLM/KeyBERT) + GPT-2 insertion
│       └── results/                            # Saved outputs & evaluation metrics for 140 encounters
│
├── agentic-pipeline/                           # Multi-agent clinical consultation pipeline (Aegle + Qwen3-14B)
│   ├── generate_soap.sh                        # One-command launcher for multi-agent consultations
│   ├── req.txt                                 # Dependencies for LangGraph agentic pipeline
│   ├── Qwen3-14B_setup/                        # 4-GPU FastAPI model server (host.py, run.sh) for Qwen/Qwen3-14B
│   ├── agentic_pipeline/                       # Core Python package (Orchestrator, Specialists, Aggregator, PatientAgent)
│   ├── prompts/                                # English MDT prompts (original_en/) & ACI-Bench grounding rules (adaptations/)
│   └── tests/                                  # Unit and integration tests (test_pipeline.py)
│
├── agentic-pipeline-output/                    # Generated outputs from the multi-agent consultation pipeline
│   └── soap_notes/                             # 110 encounter folders (D2N001..D2N116) with consultation.md & soap_note.md
│
└── verify_and_ask_pipeline/                    # Proposed RQ1 Verify-and-Ask pipeline (S/O verification, recovery & Ask)
    ├── run_local.ps1                           # Unified Windows PowerShell entry point for setup, run, and evaluation
    ├── requirements.txt                        # Combined Python dependencies
    ├── stage1_pipeline/                        # Stage 1: Strict source-grounded SOAP generation & S/O vs A/P splitting
    │   ├── stage1_code/                        # prepare_dataset.py, run_stage1.py, evaluate_stage1.py, soap_parse.py
    │   └── stage1_output/                      # Prepared 110-case dataset (22 dev / 88 test) & Stage 1 generated notes
    └── Stage23_pipeline/                       # Stage 2 (Verification) + Stage 3a (Omissions) + Stage 3b (Ask) + Evaluation
        ├── code/                               # verification.py, omission.py, ask.py, controller.py, evaluate.py, etc.
        └── output/                             # Per-case outputs, final_notes/, unsupported_claims/, and evaluation results
```

---

## 3. Folder Descriptions

| Folder | Description |
| :--- | :--- |
| **`aci-bench-corpus/`** | <ul><li>Contains the raw **ACI-Bench** corpus (207 doctor–patient conversations and reference clinical notes).</li><li>`challenge_data/` holds the 5 official splits (`train`, `valid`, `test1`, `test2`, `test3`) and patient metadata CSVs.</li><li>`src_experiment_data/` holds ASR, ASR-corrected, and human transcript variants.</li></ul> |
| **`Baseline_Implementation/`** | <ul><li>Implements the **uMedSum (ACL 2025)** 3-stage baseline adapted for full SOAP notes.</li><li>`aci_dataset_rq1_baseline/`: Zero-leakage dataset preparation with 3 fixed ICL examples and 120 / 140 / 204 evaluation splits.</li><li>`umedsum_pipeline_baseline/`:<ul><li>**Stage 1**: LLaMA-3-8B Element-Aware + 1-shot ICL generator</li><li>**Stage 2**: DeBERTa-v3-large RTB-TS confabulation remover</li><li>**Stage 3**: MiniLM/KeyBERT + GPT-2 missing-info merger</li><li>`results/`: Final outputs and evaluation scores for 140 encounters</li></ul></li></ul> |
| **`agentic-pipeline/`** | <ul><li>Implements the **Aegle** multi-disciplinary team (MDT) clinical intake workflow using **LangGraph**.</li><li>Includes a 4-GPU **Qwen3-14B** FastAPI server setup (`Qwen3-14B_setup/`).</li><li>Runs an **Orchestrator**, parallel **Specialists**, and an **Aggregator** to interview a **Standardized Patient Agent** (grounded in ACI-Bench dialogues) for up to 15 turns before freezing case features and writing the SOAP note.</li></ul> |
| **`agentic-pipeline-output/`** | <ul><li>Stores the **110 simulated clinical encounters** (`D2N001`–`D2N116`) produced by `agentic-pipeline/`.</li><li>Each encounter directory contains:<ul><li>`consultation.md`: Simulated doctor–patient dialogue</li><li>`soap_note.md`: Multi-agent generated SOAP note</li><li>`soap_note.json`: Structured agent state and metadata</li><li>`agent_conversation.md`: Full internal multi-agent reasoning trace</li></ul></li></ul> |
| **`verify_and_ask_pipeline/`** | <ul><li>Implements our proposed **Verify-and-Ask (RQ1)** architecture on the 110 simulated consultations (**22 dev** / **88 test** cases).</li><li>**Stage 1 (`stage1_pipeline/`)**: Generates a SOAP note using LLaMA-3-8B and separates `S/O` from `A/P` (keeping `A/P` untouched).</li><li>**Stage 2 (`Stage23_pipeline/code/verification.py`)**: Performs sentence-first NLI verification, contradiction rewriting, and audit logging.</li><li>**Stage 3a (`Stage23_pipeline/code/omission.py`)**: Detects low-coverage patient statements, rewrites them into third-person clinical sentences, validates NLI entailment and non-duplication, and places them via GPT-2 perplexity.</li><li>**Stage 3b (`Stage23_pipeline/code/ask.py`)**: Identifies unresolved clinical gaps and generates de-duplicated clarifying questions.</li></ul> |

---

## 4. Running Commands

### A. Baseline Pipeline (`Baseline_Implementation/`)

#### 1. Install Dependencies & Start Ollama
```bash
cd Baseline_Implementation/umedsum_pipeline_baseline
pip install -r requirements.txt
ollama serve
ollama pull llama3:8b
```

#### 2. Prepare Zero-Leakage Dataset Splits (Optional — Already Generated)
```bash
python ../aci_dataset_rq1_baseline/prepare_datasets.py
```

#### 3. Run Full Baseline Pipeline (Stages 1 $\rightarrow$ 2 $\rightarrow$ 3 $\rightarrow$ Evaluation)
```bash
# Smoke test on 1 sample:
python run_all_stages.py --limit 1

# Run on the 120-sample test split:
python run_all_stages.py --input-json ../aci_dataset_rq1_baseline/test_only/test.json

# Run on the 140-sample test+val split:
python run_all_stages.py --input-json ../aci_dataset_rq1_baseline/test+val/test_val_shuffled.json
```

#### 4. Run Individual Baseline Stages or Standalone Evaluation
```bash
# Stage 1: Initial Summary Generation (Element-Aware + 1-shot ICL)
python stage_1/stage1_generator.py \
  --input-json ../aci_dataset_rq1_baseline/test+val/test_val_shuffled.json \
  --output-json stage_1/stage1_output.json \
  --n-shots 1

# Stage 2: Confabulation Removal (RTB-TS: Te=0.9, Tc=0.8, Ta=0.5)
python stage_2/stage2_runner.py \
  --input-json stage_1/stage1_output.json \
  --output-json stage_2/stage2_output.json \
  --te 0.9 --tc 0.8 --ta 0.5

# Stage 3: Missing Information Addition (top_m=2, cov_min=0.4)
python stage_3/stage3_runner.py \
  --input-json stage_2/stage2_output.json \
  --output-json stage_3/stage3_output.json \
  --top-m 2 --cov-min 0.4

# Evaluate all stages (ROUGE, BERTScore, SummaC-Conv, QuestEval, Entailment)
python evaluate_metrics.py \
  --input-json results/stage3_output.json \
  --output-json results/evaluation_results.json
```

---

### B. Multi-Agent Consultation Pipeline (`agentic-pipeline/`)

#### 1. Start the 4-GPU Qwen3-14B Server (on GPU Node)
```bash
cd agentic-pipeline/Qwen3-14B_setup
bash run.sh --setup-only   # First time only: creates .venv and downloads Qwen/Qwen3-14B
bash run.sh --serve-only   # Starts FastAPI endpoint on http://127.0.0.1:8000
```

#### 2. Forward Port 8001 to GPU Server & Run Consultations (Local Machine)
```bash
# Verify endpoint connectivity
cd agentic-pipeline
bash generate_soap.sh --check

# Run all splits (or a specific split/encounter)
bash generate_soap.sh
bash generate_soap.sh --split train --encounter-id D2N001

# Resume an interrupted run
bash generate_soap.sh --resume
```

---

### C. Proposed Verify-and-Ask Pipeline (`verify_and_ask_pipeline/`)

#### Option 1: Using the Unified PowerShell Runner on Windows (Recommended)
```powershell
cd verify_and_ask_pipeline

# 1. Create Python 3.12 virtual environment and install requirements
.\run_local.ps1 setup

# 2. Configure API keys and server URLs (or set NLI_BASE_URL="" / EMBED_BASE_URL="" to run locally)
$env:LLM_API_KEY = "<your-llm-key>"
$env:NLI_API_KEY = "<your-nli-key>"
$env:PYTHONIOENCODING = "utf-8"

# 3. Check LLM server reachability and context size
.\run_local.ps1 check

# 4. Prepare dataset from agentic-pipeline-output/soap_notes (22 dev / 88 test, seed=42)
.\run_local.ps1 prepare

# 5. Run Stage 1 generation + Stage 1 evaluation
.\run_local.ps1 stage1

# 6. Run Stage 2 verification and Stage 3 (omission recovery + Ask) on Dev & Test splits
.\run_local.ps1 stage23 --stage2-only --split dev
.\run_local.ps1 stage23 --split dev --reuse-stage2
.\run_local.ps1 eval --split dev

.\run_local.ps1 stage23 --split test --reuse-stage2
.\run_local.ps1 eval --split test
```

#### Option 2: Running Python Scripts Directly (Local Ollama or Remote Server)
```bash
# Stage 1: Prepare dataset, generate SOAP notes, and evaluate Stage 1 S/O
cd verify_and_ask_pipeline/stage1_pipeline/stage1_code
python prepare_dataset.py
python run_stage1.py
python evaluate_stage1.py

# Stage 2 & 3: Run verification, omission recovery, Ask, and 3-phase evaluation
cd ../../Stage23_pipeline/code
python run_stage23.py --limit 3 --no-ask --no-gpt2   # Smoke test
python run_stage23.py --split dev                    # Run on dev split (22 cases)
python evaluate.py --split dev                       # Evaluate dev split
python run_stage23.py --split test                   # Run on test split (88 cases)
python evaluate.py --split test                      # Evaluate test split
```
