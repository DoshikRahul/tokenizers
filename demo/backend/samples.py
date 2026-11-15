"""Read-only access to the project's saved agentic-pipeline outputs.

Each folder in agentic-pipeline-output/soap_notes/<ID>/ is converted into the
same event stream the live pipeline emits, so the UI can replay it.
"""
from __future__ import annotations

import csv
import json
import re
from functools import lru_cache
from pathlib import Path

from sessions import FIELD_LABELS

HEADER = re.compile(r"^## (\d+)\. Turn (\d+) — (.+?)\s*$", re.M)
ROUTE = re.compile(r"^\*\*(.+?) → (.+?)\*\* · (.+?)\s*$")
SAFE_ID = re.compile(r"^D2N\d{3}$")
LABEL_TO_FIELD = {label: field for field, label in FIELD_LABELS.items()}


class Samples:
    def __init__(self, output_root: Path, dataset_dir: Path):
        self.root = output_root
        self.dataset_dir = dataset_dir

    def _folder(self, encounter_id: str) -> Path:
        if not SAFE_ID.match(encounter_id):
            raise KeyError("Unknown encounter id.")
        folder = self.root / encounter_id
        if not (folder / "soap_note.json").is_file():
            raise KeyError(f"No saved output for {encounter_id}.")
        return folder

    @lru_cache(maxsize=1)
    def splits(self) -> dict[str, str]:
        from agentic_pipeline.dataset import SPLITS

        result = {}
        for split, filename in SPLITS.items():
            path = self.dataset_dir / "challenge_data" / filename
            if path.is_file():
                with path.open(newline="", encoding="utf-8-sig") as handle:
                    for row in csv.DictReader(handle):
                        result[row["encounter_id"]] = split
        return result

    def list(self) -> list[dict]:
        items = []
        splits = self.splits()
        for folder in sorted(self.root.glob("D2N*")):
            path = folder / "soap_note.json"
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            basic = (data.get("case_features") or {}).get("basic_info", "")
            items.append({"encounter_id": folder.name, "split": splits.get(folder.name, "?"),
                          "turns": data.get("turns"), "stop_reason": data.get("stop_reason"),
                          "specialists": data.get("activated_specialists", []),
                          "summary": basic[:160]})
        return items

    def dialogue(self, encounter_id: str) -> str | None:
        from agentic_pipeline.dataset import load_encounters

        split = self.splits().get(encounter_id)
        if not split or not SAFE_ID.match(encounter_id):
            return None
        return load_encounters(self.dataset_dir, split, encounter_id, 1)[0].dialogue

    def events(self, encounter_id: str) -> dict:
        folder = self._folder(encounter_id)
        soap = json.loads((folder / "soap_note.json").read_text(encoding="utf-8"))
        text = (folder / "agent_conversation.md").read_text(encoding="utf-8")
        events: list[dict] = []
        matches = list(HEADER.finditer(text))
        for position, match in enumerate(matches):
            end = matches[position + 1].start() if position + 1 < len(matches) else len(text)
            body = text[match.end():end].strip()
            turn, phase = int(match[2]), match[3].strip().replace(" ", "_")
            first, _, content = body.partition("\n")
            route = ROUTE.match(first.strip())
            if not route:
                continue
            sender, recipient, kind = route[1].strip(), route[2].strip(), route[3].strip()
            content = content.strip()
            if kind == "question":
                events.append({"type": "chat", "role": "doctor", "turn": turn, "content": content})
            elif kind == "answer":
                events.append({"type": "chat", "role": "patient", "turn": turn, "content": content})
            elif kind == "evidence frozen":
                events.append({"type": "frozen", "turn": turn, "stop_reason": soap.get("stop_reason"),
                               "uncollected": soap.get("uncollected_fields", [])})
            elif kind == "resumed":
                continue
            else:
                events.append({"type": "agent", "agent": sender, "recipient": recipient, "kind": kind,
                               "phase": phase, "turn": turn, "content": content})
                if kind == "evidence update":
                    features = {field: "" for field in FIELD_LABELS}
                    complete = False
                    for line in content.split("\n\n"):
                        found = re.match(r"^\*\*(.+?):\*\*\s*(.*)$", line.strip(), re.S)
                        if not found:
                            continue
                        label, value = found[1], found[2].strip()
                        if label in LABEL_TO_FIELD:
                            features[LABEL_TO_FIELD[label]] = "" if value == "Not yet collected." else value
                        elif label == "History complete":
                            complete = value.lower() == "true"
                    events.append({"type": "features", "turn": turn, "features": features, "complete": complete})
        events.append({"type": "soap", "soap": soap.get("soap", {}), "meta": {
            "turns": soap.get("turns"), "stop_reason": soap.get("stop_reason"),
            "activated_specialists": soap.get("activated_specialists", []),
            "uncollected_fields": soap.get("uncollected_fields", []), "mode": "replay",
            "encounter_id": encounter_id}})
        return {"encounter_id": encounter_id, "split": self.splits().get(encounter_id), "events": events,
                "source_dialogue": self.dialogue(encounter_id)}
