"""Load case folders containing consultation.md and soap_note.md.

The ground-truth note is read only to extract reference Subjective and Objective
sections for evaluation. run_stage1.py passes only `conversation` to the LLM.
"""
import json
import random
import sys
from pathlib import Path
from config import DATASET_ROOT, OUTPUT_DIR, PREPARED_JSON, SPLIT_SEED, DEV_FRACTION
from soap_parse import extract_section, clean_conversation


def read_markdown(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig").strip()


def find_pairs(root: Path):
    if not root.exists():
        raise FileNotFoundError(
            f"Dataset directory not found: {root}\n"
            "Set DATASET_ROOT to the directory containing your case folders."
        )
    for consultation in sorted(root.rglob("consultation.md")):
        soap = consultation.with_name("soap_note.md")
        if soap.exists():
            yield consultation, soap
        else:
            print(f"[WARN] Missing soap_note.md beside {consultation}", file=sys.stderr)

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    records = []
    skipped = 0

    for consultation_path, soap_path in find_pairs(DATASET_ROOT):
        try:
            conversation = clean_conversation(read_markdown(consultation_path))
            soap = read_markdown(soap_path)

            # Extract all four ground-truth SOAP sections.
            ref_s = extract_section(soap, "Subjective")
            ref_o = extract_section(soap, "Objective")
            ref_a = extract_section(soap, "Assessment")
            ref_p = extract_section(soap, "Plan")

            if not conversation:
                print(
                    f"[WARN] Empty conversation: {consultation_path}",
                    file=sys.stderr,
                )
                skipped += 1
                continue

            # Require at least Subjective or Objective for S/O evaluation.
            if not ref_s and not ref_o:
                print(
                    f"[WARN] Could not extract Subjective/Objective: {soap_path}",
                    file=sys.stderr,
                )
                skipped += 1
                continue

            records.append({
                "case_id": consultation_path.parent.name,

                # This is the ONLY field the generation model should receive.
                "conversation": conversation,

                # All four reference sections are saved for reference/storage.
                "reference_soap": {
                    "subjective": ref_s,
                    "objective": ref_o,
                    "assessment": ref_a,
                    "plan": ref_p,
                },

                # Keep this field for compatibility with evaluate_stage1.py.
                "reference_so": {
                    "subjective": ref_s,
                    "objective": ref_o,
                },

                "source_paths": {
                    "consultation": str(consultation_path),
                    "soap_note": str(soap_path),
                },
            })

        except (OSError, UnicodeError) as exc:
            print(
                f"[WARN] Skipping {consultation_path.parent}: {exc}",
                file=sys.stderr,
            )
            skipped += 1

    if not records:
        raise RuntimeError(
            f"No usable cases found under {DATASET_ROOT}. Expected each case "
            "folder to contain consultation.md and soap_note.md."
        )

    # Seeded dev/test split, stable across runs.
    ids = sorted(r["case_id"] for r in records)
    random.Random(SPLIT_SEED).shuffle(ids)
    n_dev = round(len(ids) * DEV_FRACTION)
    dev_ids = set(ids[:n_dev])
    for r in records:
        r["split"] = "dev" if r["case_id"] in dev_ids else "test"

    payload = {
        "split_seed": SPLIT_SEED,
        "dev_fraction": DEV_FRACTION,
        "num_dev": n_dev,
        "num_test": len(records) - n_dev,
        "dataset_root": str(DATASET_ROOT.resolve()),
        "num_cases": len(records),
        "num_skipped": skipped,
        "records": records,
    }

    PREPARED_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Prepared {len(records)} cases ({n_dev} dev / {len(records) - n_dev} test); skipped {skipped}.")
    print(f"Output: {PREPARED_JSON}")


if __name__ == "__main__":
    main()
