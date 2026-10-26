"""Read only the canonical challenge splits; never expose a reference note to agents."""
import csv
from dataclasses import dataclass
from pathlib import Path

SPLITS = {
    "train": "train.csv", "valid": "valid.csv",
    "test1": "clinicalnlp_taskB_test1.csv", "test2": "clinicalnlp_taskC_test2.csv",
    "test3": "clef_taskC_test3.csv",
}


@dataclass(frozen=True)
class Encounter:
    split: str
    encounter_id: str
    dataset: str
    dialogue: str
    source_file: str


def load_encounters(dataset_dir: Path, split: str, encounter_id: str | None, limit: int) -> list[Encounter]:
    if limit < 0:
        raise ValueError("--limit must be nonnegative; 0 means all selected encounters.")
    selected = list(SPLITS) if split == "all" else [split]
    result = []
    seen = set()
    for label in selected:
        path = dataset_dir / "challenge_data" / SPLITS[label]
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if not {"dataset", "encounter_id", "dialogue"}.issubset(reader.fieldnames or []):
                raise ValueError(f"Unexpected columns in {path}")
            for row in reader:
                identifier = row["encounter_id"]
                if identifier in seen:
                    raise ValueError(f"Duplicate encounter ID: {identifier}")
                seen.add(identifier)
                if encounter_id is not None and identifier != encounter_id:
                    continue
                if not row["dialogue"].strip():
                    raise ValueError(f"Empty dialogue in {path}: {identifier}")
                # Deliberately select these fields. No note or clinical metadata is retained.
                result.append(Encounter(label, identifier, row["dataset"], row["dialogue"], str(path.resolve())))
    if encounter_id is not None and not result:
        raise ValueError(f"Encounter {encounter_id!r} was not found in split {split!r}.")
    return result[:limit] if limit else result
