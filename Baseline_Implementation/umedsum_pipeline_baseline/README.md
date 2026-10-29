# uMedSum Baseline Pipeline (Full SOAP Note Implementation)

End-to-end implementation and evaluation benchmark for *"uMedSum: A Unified Framework for Clinical Abstractive Summarization"* (Nagar et al., ACL 2025, pp. 2653–2672).

Evaluated on the **ACI-BENCH** clinical dialogue dataset for generating and verifying **Complete Clinical SOAP Notes** (Subjective, Objective, Assessment and Plan).

---

## 1. Architecture & Directory Structure

```text
umedsum_pipeline_baseline/
|-- requirements.txt                       # Unified environment dependencies
|-- run_all_stages.py                      # Master runner (Stages 1 -> 2 -> 3 -> Evaluation -> Results)
|-- evaluate_metrics.py                    # Multi-stage benchmark evaluation (ROUGE-1/2/L, BERTScore, etc.)
|
|-- results/                               # Master Results & Evaluation Archive
|   |-- stage1_output.json                 # Stage 1 generated notes & extracted clinical elements
|   |-- stage2_output.json                 # Stage 2 purged notes, NLI scores, and dialogue citations
|   |-- stage3_output.json                 # Stage 3 final refined notes & added missing facts
|   `-- evaluation_results.json            # Final benchmark evaluation scores & aggregate tables
|
|-- stage_1/                               # Stage 1: Initial Summary Generation (Paper SOTA)
|   |-- prompts.py                         # Element-Aware extraction & 3-shot ICL SOAP synthesis prompts
|   |-- ollama_client.py                   # Zero-dependency Ollama REST client
|   |-- stage1_generator.py                # Main Stage 1 runner (LLaMA 3 8B via Ollama)
|   |-- stage1_output.json                 # Stage 1 generated output
|   `-- README.md
|
|-- stage_2/                               # Stage 2: Confabulation Removal (RTB-TS)
|   |-- nli_scorer.py                      # DeBERTa-v3-large batched NLI scorer across dialogue chunks
|   |-- atomic_decomposer.py               # LLaMA 3 atomic fact decomposition for uncertain claims
|   |-- confabulation_remover.py           # Recursive Threshold-Based Text Segmentation (Te=0.9, Tc=0.8, Ta=0.5)
|   |-- stage2_runner.py                   # Main Stage 2 runner
|   |-- stage2_output.json                 # Stage 2 purged summaries & citations
|   `-- README.md
|
`-- stage_3/                               # Stage 3: Missing Information Addition
    |-- key_extractor.py                   # Sentence-BERT (all-MiniLM-L6-v2) MMR ranking & KeyBERT
    |-- missing_detector.py                # Dense cosine similarity & coverage threshold (cov_min=0.4)
    |-- perplexity_merger.py               # GPT-2 fluency LM perplexity minimization & greedy insertion
    |-- stage3_runner.py                   # Main Stage 3 runner
    |-- stage3_output.json                 # Final uMedSum clinical notes
    `-- README.md
```

---

## 2. Data Flow & What Each Stage Checks

```text
               Raw Dialogue ("src")
                        │
                        ▼
    ┌───────────────────────────────────────┐
    │  STAGE 1: GENERATION (LLaMA 3 8B)     │
    │  • Step 1: Extracts S, O, A, P items  │ ──> Produces Draft SOAP Note
    │  • Step 2: Synthesizes Full SOAP Note │     (stage1_summary)
    └───────────────────┬───────────────────┘
                        │
                        ▼
    ┌───────────────────────────────────────┐
    │  STAGE 2: CONFABULATION REMOVAL (NLI) │
    │  • Segments note into units & sections│
    │  • DeBERTa-v3-large tests each unit:  │
    │    - E > 0.9  ──> Faithful (cites src)│ ──> Purges unsupported claims
    │    - N+C > 0.8──> Discard (logs why)  │     (stage2_summary)
    │    - Else     ──> Atomic decomposition│
    └───────────────────┬───────────────────┘
                        │
                        ▼
    ┌───────────────────────────────────────┐
    │  STAGE 3: MISSING ADDITION (MiniLM)   │
    │  • MMR extracts top dialogue sentences│ ──> Pastes missing dialogue facts
    │  • If Coverage < 0.40:                │     via GPT-2 perplexity
    │    GPT-2 inserts in smoothest position│     (stage3_summary)
    └───────────────────┬───────────────────┘
                        │
                        ▼
    ┌───────────────────────────────────────┐
    │  BENCHMARK EVALUATION (evaluate)      │ ──> Evaluates Stages 1, 2, 3
    │  • Scores ROUGE & BERTScore vs `tgt`  │     vs Doctor Reference Note
    │  • Saves to results/evaluation_...json│
    └───────────────────────────────────────┘
```

### What Each Stage Checks:

#### 1. Input Data (`aci_dataset_rq1_baseline/`)
Each sample contains:
- `src`: Raw conversational audio transcript between doctor and patient (~1,500 words).
- `tgt` / `tgt_full`: Complete reference SOAP Note written by the human doctor.
- `tgt_subjective`: Human doctor reference for Chief Complaint, HPI, and ROS.
- `tgt_objective_exam` & `tgt_objective_results`: Human doctor reference for physical examination and lab findings.
- `tgt_assessment_and_plan`: Human doctor reference for diagnoses and treatment plans.

#### 2. Stage 1 Checks & Transforms
- **Step 1 (Element Extraction):** Identifies factual clinical elements (symptoms, durations, medications, allergies, physical exam findings, vital signs, diagnoses, and orders).
- **Step 2 (SOAP Synthesis):** Organizes elements under standard clinical headings:
  - `SUBJECTIVE`: Chief Complaint, HPI, medical history.
  - `OBJECTIVE`: Physical exam vitals, lung/heart auscultation, lab results.
  - `ASSESSMENT AND PLAN`: Diagnoses, medical reasoning, prescriptions, follow-up.

#### 3. Stage 2 Checks & Transforms (Confabulation Removal)
- Segments the note into clinical units and classifies their section:
  - `[SUBJECTIVE]`: Symptoms, patient history, duration.
  - `[OBJECTIVE]`: Vitals, exam observations, labs.
  - `[ASSESSMENT_AND_PLAN]`: Diagnoses, clinical reasoning, orders.
- Evaluates each unit against the dialogue using `DeBERTa-v3-large`:
  - **Faithful ($E > 0.9$):** Cites the exact supporting dialogue turn from `src`.
  - **Confabulated / Discarded ($N + C > 0.8$):** Discards the claim. If the statement is an Assessment/Plan diagnosis, logs clinical reasoning explaining that it is a diagnostic inference purged by uniform entailment.
  - **Uncertain ($0.5 \le E \le 0.9$):** Decomposes into atomic sub-propositions and re-scores.

#### 4. Stage 3 Checks & Transforms (Missing Information Addition)
- Uses Sentence-BERT (`all-MiniLM-L6-v2`) and MMR to extract the most medically informative sentences from the dialogue (`src`).
- Computes cosine similarity coverage against summary key phrases (extracted via `KeyBERT`).
- If coverage $< 0.40$ (Eq. 7 of paper), flags the finding as missing from the note and inserts it using GPT-2 perplexity minimization.

#### 5. Evaluation Checks
- Compares `stage1_summary`, `stage2_summary`, and `stage3_summary` directly against the human doctor reference note (`tgt_full`).
- Computes ROUGE-1, ROUGE-2, ROUGE-L, ROUGE-Lsum, BERTScore F1, Word Count, and Compression Ratio.

---

## 3. The `results/` Directory

All outputs and evaluation reports are archived in the `results/` folder:

| File | What It Contains |
| :--- | :--- |
| `results/stage1_output.json` | Stage 1 generated full SOAP notes, extracted elements, method metadata. |
| `results/stage2_output.json` | Stage 2 purged SOAP notes, section breakdowns, NLI scores, exact dialogue citations, and diagnostic reasoning. |
| `results/stage3_output.json` | Stage 3 final refined notes, dialogue key sentences evaluated, coverage scores, and added sentences. |
| `results/evaluation_results.json` | Complete benchmark metric scores (ROUGE-1/2/L, word counts, compression ratios) across all stages. |

---

## 4. How to Run

### Option A: One-Command Master Execution (Recommended)
Runs the full pipeline end-to-end, performs automatic evaluation, and archives all files to `results/`:

```bash
# Run 1 sample locally for verification:
python run_all_stages.py --limit 1

# Run without re-generating Stage 1 (uses existing stage1_output.json):
python run_all_stages.py --limit 1 --skip-stage1

# Run the complete test benchmark split (120 samples):
python run_all_stages.py --input-json ../aci_dataset_rq1_baseline/test_only/test.json
```

### Option B: Running Individual Stages Standalone

#### Stage 1: Initial Summary Generation
```bash
python stage_1/stage1_generator.py \
  --input-json ../aci_dataset_rq1_baseline/test_only/test.json \
  --output-json stage_1/stage1_output.json \
  --n-shots 1
```

#### Stage 2: Confabulation Removal (RTB-TS)
```bash
python stage_2/stage2_runner.py \
  --input-json stage_1/stage1_output.json \
  --output-json stage_2/stage2_output.json \
  --te 0.9 --tc 0.8 --ta 0.5
```

#### Stage 3: Missing Information Addition
```bash
python stage_3/stage3_runner.py \
  --input-json stage_2/stage2_output.json \
  --output-json stage_3/stage3_output.json \
  --top-m 2 --cov-min 0.4
```

#### Run Multi-Stage Benchmark Evaluation:
```bash
# Fast evaluation (ROUGE + Compression + Audit Stats):
python evaluate_metrics.py --input-json results/stage3_output.json --output-json results/evaluation_results.json --skip-bertscore

# Full evaluation with BERTScore (roberta-large):
python evaluate_metrics.py --input-json results/stage3_output.json --output-json results/evaluation_results.json
```

---

## 5. Benchmark Results on Sample 1 (`D2N088`)

```text
============================================================================================
                    uMedSum BENCHMARK EVALUATION RESULTS
============================================================================================
Pipeline Stage         | R-1     | R-2     | R-L     | R-Lsum  | BERTScore | Words  | Comp. 
--------------------------------------------------------------------------------------------
Stage 1 (Initial ICL)  | 0.3414  | 0.1341  | 0.2076  | 0.3368  | N/A       | 232.0  | 0.148 
Stage 2 (Purged RTB-TS)| 0.2269  | 0.0889  | 0.1486  | 0.2034  | N/A       | 112.0  | 0.072 
Stage 3 (Final uMedSum)| 0.2525  | 0.0987  | 0.1465  | 0.2298  | N/A       | 145.0  | 0.093 
--------------------------------------------------------------------------------------------
Paper SOTA (Table 1)   | ~0.44   | ~0.22   | ~0.40   | ~0.42   | ~0.86     | ~140   | ~0.09 
============================================================================================
```

---

## 6. Google Colab GPU Guide (T4 / A100)

The entire codebase auto-detects CUDA (`cuda` if available, else `cpu`) with zero code modifications needed.

### Estimated Runtimes for Full SOAP Notes:
| Split | Local CPU | Colab T4 (16 GB) | Colab A100 (40 GB) |
| :--- | :---: | :---: | :---: |
| **1 Sample** (Test Run) | ~28.5 min | **~8.5 sec** | **~2.4 sec** |
| **`test_only` (120 samples)** | ~57 hours | **~17 min** | **~5 min** |
| **`test+val` (140 samples)** | ~66 hours | **~20 min** | **~6 min** |
| **`test+val+train` (204 samples)** | ~97 hours | **~29 min** | **~8 min** |

### Colab Setup Cell:
```python
# 1. Install Ollama and Python packages
!curl -fsSL https://ollama.com/install.sh | sh
!pip install -q torch transformers sentence-transformers keybert pysbd bert-score rouge-score accelerate

# 2. Start Ollama in background & pull LLaMA 3
import subprocess, time
subprocess.Popen(["ollama", "serve"])
time.sleep(3)
!ollama pull llama3:8b

# 3. Run complete pipeline and save to results/
!python run_all_stages.py --input-json ../aci_dataset_rq1_baseline/test_only/test.json
```
