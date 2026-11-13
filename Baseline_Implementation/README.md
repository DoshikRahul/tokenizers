# Baseline Implementation (`uMedSum`)

This directory contains our baseline implementation of **uMedSum** (*"uMedSum: A Unified Framework for Clinical Abstractive Summarization"*, Nagar et al., ACL 2025) and its evaluation setups.

---

## Primary RQ1 Comparison Baseline

The two artifacts below form the **main baseline** compared against our **Verify-and-Ask (RQ1)** system on the 110 simulated clinical consultations (`22 dev / 88 test`, seed 42):

### `umedsum_final_soap_notes/`
Main baseline folder used for direct side-by-side comparison with Verify-and-Ask (RQ1). It imports the Stage 1–3 algorithms from `umedsum_pipeline_baseline/` and adapts section handling to match the RQ1 evaluation setup:

- **`run_umedsum_soap.py`** — End-to-end runner on `verify_and_ask_pipeline/stage1_pipeline/stage1_output/prepared_dataset.json`:
  - **Stage 1:** Element-Aware + 1-shot ICL full-SOAP generation (LLaMA-3-8B), split into Subjective/Objective (`S/O`) and Assessment/Plan (`A/P`). `A/P` is kept aside and passed through unchanged.
  - **Stage 2:** RTB-TS confabulation removal on `S/O` only (DeBERTa-v3-large NLI, `Te=0.9`, `Tc=0.8`, `Ta=0.5`), with `FixedHeaderRemover` enabled by default so only real heading lines are stripped before NLI scoring.
  - **Stage 3:** MMR key-sentence extraction + KeyBERT coverage (`cov_min=0.4`, `top_m=2`) + GPT-2 perplexity-minimizing insertion on `S/O` only.
  - **Final output:** Stage 3 `S/O` + untouched Stage 1 `A/P`, saved in the Verify-and-Ask record schema so `verify_and_ask_pipeline/Stage23_pipeline/code/evaluate.py` scores both systems identically.
- **`compare_results.py`** — Produces side-by-side comparison tables (`comparison_<split>.md` / `.json`) and per-case paired statistical tests (`paired_tests_<split>.csv` with 95% bootstrap CI and Wilcoxon signed-rank p-value) between uMedSum and Verify-and-Ask.
- **`output/`** — Saved baseline run artifacts, including `umedsum_output.json`, per-case JSONs (`output/cases/`), and final generated SOAP notes (`output/final_notes/`).

### `final_umedsum_on_soap_notes.ipynb`
Google Colab notebook that executes the RQ1-matched uMedSum baseline (`umedsum_final_soap_notes/run_umedsum_soap.py`) on GPU across the 110 simulated consultations, runs `Stage23_pipeline/code/evaluate.py`, and compares results against Verify-and-Ask.

---

## Other Contents (Brief Overview)

- **`aci_dataset_rq1_baseline/`** — Dataset preparation script (`prepare_datasets.py`), 3 fixed ICL demonstrations (`icl_examples.json`), and zero-leakage ACI-BENCH splits (`test_only/`, `test+val/`, `test+val+train/`).
- **`umedsum_pipeline_baseline/`** — Core modular 3-stage uMedSum implementation (`stage_1/`, `stage_2/`, `stage_3/`), master runner (`run_all_stages.py`), evaluation script (`evaluate_metrics.py`), and ACI-BENCH baseline results (`results/`).
- **`tokenizer's_umedsum_baseline.ipynb`** — Earlier Colab notebook used to run the initial uMedSum baseline on ACI-BENCH.
