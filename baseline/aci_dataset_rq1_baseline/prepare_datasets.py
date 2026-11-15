"""
Enhanced Data Preparation Script for uMedSum Full SOAP Note Benchmark (Subjective + Objective + A/P).

Prepares three evaluation dataset configurations under `aci_dataset_rq1_baseline/`:
1. `test_only`: 120 samples (test1 + test2 + test3)
2. `test+val`: 140 samples (test + val, plus merged shuffled version)
3. `test+val+train`: 204 samples (test + val + train_eval, plus merged shuffled version)

Common:
- `icl_examples.json`: 3 fixed demonstrations extracted from train (1 virtassist, 1 virtscribe, 1 aci),
  guaranteeing zero overlap and completely preventing leakage.
- Targets included per sample:
  `tgt`: Full SOAP Note (Subjective, Objective, Assessment and Plan)
  `tgt_full`: Full ground truth note
  `tgt_subjective`: Subjective section (Chief Complaint, HPI, ROS)
  `tgt_objective_exam`: Physical Examination findings
  `tgt_objective_results`: Diagnostic results and lab values
  `tgt_assessment_and_plan`: Assessment & Plan section
- Enhanced metadata: `encounter_id`, `source_dataset`, and `original_split`.
"""

import json
import os
import random
from pathlib import Path
from copy import deepcopy

RANDOM_SEED = 42
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

potential_paths = [
    BASE_DIR.parent / "aci-bench" / "data" / "challenge_data_json",
    BASE_DIR.parent / "data" / "challenge_data_json",
]
SOURCE_JSON_DIR = next((p for p in potential_paths if p.exists()), potential_paths[0])

# Fixed ICL encounters set aside from train (1 from each data source)
DEFAULT_ICL_ENCOUNTER_IDS = ["D2N002", "D2N023", "D2N035"]

SPLIT_PREFIXES = {
    "train": "train",
    "valid": "valid",
    "test1": "clinicalnlp_taskB_test1",
    "test2": "clinicalnlp_taskC_test2",
    "test3": "clef_taskC_test3",
}


def load_and_merge_encounter_sections(split_name: str, prefix: str) -> list:
    """Loads and merges full note + individual sections for every encounter in split."""
    p_full = SOURCE_JSON_DIR / f"{prefix}_full.json"
    p_sub = SOURCE_JSON_DIR / f"{prefix}_subjective.json"
    p_exam = SOURCE_JSON_DIR / f"{prefix}_objective_exam.json"
    p_res = SOURCE_JSON_DIR / f"{prefix}_objective_results.json"
    p_ap = SOURCE_JSON_DIR / f"{prefix}_assessment_and_plan.json"

    with open(p_full, "r", encoding="utf-8") as f:
        data_full = json.load(f)["data"]
    with open(p_sub, "r", encoding="utf-8") as f:
        data_sub = json.load(f)["data"]
    with open(p_exam, "r", encoding="utf-8") as f:
        data_exam = json.load(f)["data"]
    with open(p_res, "r", encoding="utf-8") as f:
        data_res = json.load(f)["data"]
    with open(p_ap, "r", encoding="utf-8") as f:
        data_ap = json.load(f)["data"]

    assert len(data_full) == len(data_sub) == len(data_exam) == len(data_res) == len(data_ap)

    merged_samples = []
    for i in range(len(data_full)):
        item = deepcopy(data_full[i])
        file_id = item.get("file", "")
        parts = file_id.split("-")
        encounter_id = parts[0] if len(parts) > 0 else ""
        source_dataset = parts[1] if len(parts) > 1 else ""

        item["encounter_id"] = encounter_id
        item["source_dataset"] = source_dataset
        item["original_split"] = split_name
        item["file"] = f"{encounter_id}-{source_dataset}-full"

        # Targets
        item["tgt_full"] = item["tgt"]
        item["tgt_subjective"] = data_sub[i].get("tgt", "")
        item["tgt_objective_exam"] = data_exam[i].get("tgt", "")
        item["tgt_objective_results"] = data_res[i].get("tgt", "")
        item["tgt_assessment_and_plan"] = data_ap[i].get("tgt", "")

        merged_samples.append(item)

    return merged_samples


def save_json(data: list, filepath: Path) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump({"data": data}, f, indent=2, ensure_ascii=False)
    print(f"  [SAVED] {filepath.name} ({len(data)} samples) in {filepath.parent.name}")


def prepare_all_datasets(icl_encounters: list = None):
    if icl_encounters is None:
        icl_encounters = DEFAULT_ICL_ENCOUNTER_IDS

    print(f"Loading source splits from: {SOURCE_JSON_DIR} ...")
    splits_data = {
        name: load_and_merge_encounter_sections(name, prefix)
        for name, prefix in SPLIT_PREFIXES.items()
    }

    # 1. Extract ICL examples from train
    train_samples = splits_data["train"]
    icl_samples = []
    train_eval_samples = []

    for sample in train_samples:
        if sample["encounter_id"] in icl_encounters:
            icl_samples.append(sample)
        else:
            train_eval_samples.append(sample)

    assert len(icl_samples) == len(icl_encounters), (
        f"Expected {len(icl_encounters)} ICL samples, but matched {len(icl_samples)}"
    )

    # 2. Combined Test set (test1 + test2 + test3 = 120 samples)
    test_samples = (
        splits_data["test1"] + splits_data["test2"] + splits_data["test3"]
    )
    val_samples = splits_data["valid"]

    print("\n--- Saving Common ICL Demonstrations ---")
    icl_path = BASE_DIR / "icl_examples.json"
    save_json(icl_samples, icl_path)

    # 3. Setup: test_only
    print("\n--- Preparing test_only (120 samples) ---")
    test_only_dir = BASE_DIR / "test_only"
    save_json(test_samples, test_only_dir / "test.json")

    # 4. Setup: test+val
    print("\n--- Preparing test+val (140 samples) ---")
    test_val_dir = BASE_DIR / "test+val"
    save_json(test_samples, test_val_dir / "test.json")
    save_json(val_samples, test_val_dir / "val.json")

    combined_test_val = deepcopy(test_samples + val_samples)
    rng_tv = random.Random(RANDOM_SEED)
    rng_tv.shuffle(combined_test_val)
    save_json(combined_test_val, test_val_dir / "test_val_shuffled.json")

    # 5. Setup: test+val+train
    print("\n--- Preparing test+val+train (204 samples) ---")
    test_val_train_dir = BASE_DIR / "test+val+train"
    save_json(test_samples, test_val_train_dir / "test.json")
    save_json(val_samples, test_val_train_dir / "val.json")
    save_json(train_eval_samples, test_val_train_dir / "train_eval.json")

    combined_all = deepcopy(test_samples + val_samples + train_eval_samples)
    rng_all = random.Random(RANDOM_SEED)
    rng_all.shuffle(combined_all)
    save_json(combined_all, test_val_train_dir / "test_val_train_shuffled.json")

    # 6. Sanity check & Verification
    print("\n--- Sanity Checks ---")
    icl_set = {s["encounter_id"] for s in icl_samples}
    eval_set = {s["encounter_id"] for s in combined_all}

    overlap = icl_set.intersection(eval_set)
    print(f"Overlap between ICL set and any evaluation sample: {len(overlap)}")
    assert len(overlap) == 0, f"DATA LEAK DETECTED: {overlap}"

    print(f"Total Unique Encounters in whole pool: {len(icl_set | eval_set)}")
    assert len(icl_set | eval_set) == 207, f"Expected 207 encounters, found {len(icl_set | eval_set)}"

    print("\nAll datasets created successfully without data leakage!")


if __name__ == "__main__":
    prepare_all_datasets()
