# Final Dataset Setup for RQ1 Baseline Testing

This directory contains the prepared dataset files and generation scripts for testing the uMedSum pipeline across three data configurations on ACI-BENCH.

---

## 1. Directory Structure

```text
aci_dataset_rq1_baseline/
├── README.md                              # This documentation
├── prepare_datasets.py                    # Generation & verification script
├── icl_examples.json                      # 3 fixed ICL demonstrations (common across all setups)
├── test_only/
│   └── test.json                          # 120 samples (test1 + test2 + test3)
├── test+val/
│   ├── test.json                          # 120 samples
│   ├── val.json                           # 20 samples
│   └── test_val_shuffled.json             # 140 samples (shuffled with seed=42)
└── test+val+train/
    ├── test.json                          # 120 samples
    ├── val.json                           # 20 samples
    ├── train_eval.json                    # 64 samples (train without ICL examples)
    └── test_val_train_shuffled.json       # 204 samples (shuffled with seed=42)
```

---

## 2. Sample Breakdown & Zero-Leakage Guarantee

Total encounters across ACI-BENCH: **207**.

- **ICL Demonstrations (`icl_examples.json`):**
  - **3 samples** set aside permanently from `train_assessment_and_plan.json`:
    1. `D2N002-virtassist-assessment_and_plan` (virtassist)
    2. `D2N023-virtscribe-assessment_and_plan` (virtscribe)
    3. `D2N035-aci-assessment_and_plan` (aci)
  - Zero overlap with any evaluation sample across all 3 test setups.

- **`test_only` (120 samples):**
  - Test 1 (40) + Test 2 (40) + Test 3 (40).

- **`test_plus_val` (140 samples):**
  - Test (120) + Val (20).
  - Contains separate `test.json`, `val.json`, and the deterministically shuffled combination `test_val_shuffled.json`.

- **`test_plus_val_train` (204 samples):**
  - Test (120) + Val (20) + Train evaluation (64).
  - Contains separate `test.json`, `val.json`, `train_eval.json`, and the deterministically shuffled combination `test_val_train_shuffled.json`.

---

## 3. Data Schema & Enhanced Metadata

Each sample includes the original fields plus enhanced metadata:

```json
{
  "file": "D2N001-virtassist-assessment_and_plan",
  "src": "[doctor] hi , martha ...",
  "tgt": "ASSESSMENT AND PLAN\n\n...",
  "encounter_id": "D2N001",
  "source_dataset": "virtassist",
  "original_split": "train"
}
```

The added keys (`encounter_id`, `source_dataset`, and `original_split`) allow you to calculate granular breakdowns (e.g., scoring only `test1` or only `virtscribe`) directly from the merged shuffled files.

---

## 4. Re-running / Regenerating

To re-run the preparation and verification script:
```powershell
python aci_dataset_rq1_baseline/prepare_datasets.py
```
