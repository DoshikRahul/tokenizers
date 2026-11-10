"""Shared helpers: IO, dialogue parsing, sentence splitting, resumable JSONL caches, timing."""
import csv
import json
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

csv.field_size_limit(10 ** 9)


# ---------------------------------------------------------------- IO
def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def read_jsonl(path) -> List[dict]:
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def write_jsonl(path, rows: Iterable[dict]):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_csv(path) -> List[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows: List[dict], fields: List[str] = None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or (list(rows[0].keys()) if rows else [])
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


class JsonlCache:
    """Append-only key -> record store, so long runs resume after a crash."""

    def __init__(self, path, key="statement_id"):
        self.path, self.key = Path(path), key
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data: Dict[str, dict] = {r[key]: r for r in read_jsonl(self.path)}

    def __contains__(self, k):
        return k in self.data

    def get(self, k):
        return self.data.get(k)

    def put(self, rec: dict):
        self.data[rec[self.key]] = rec
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- dialogue
def parse_aci_dialogue(text: str) -> List[dict]:
    """ACI-Bench '[doctor] ...' lines (or 'Doctor: ...') -> [{'tid':'T1','speaker':'Doctor','text':...}]."""
    turns = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^\[([^\]]+)\]\s*(.*)$", line) or re.match(r"^(Doctor|Patient)\s*:\s*(.*)$", line)
        if m:
            spk = m.group(1).strip().lower()
            spk = "Doctor" if spk.startswith("doctor") else "Patient" if spk.startswith("patient") \
                else spk.replace("_", " ").title()
            turns.append({"speaker": spk, "text": m.group(2).strip()})
        elif turns:
            turns[-1]["text"] += " " + line
    for i, t in enumerate(turns, 1):
        t["tid"] = f"T{i}"
    return turns


def turns_to_text(turns: List[dict], with_ids: bool = True) -> str:
    if with_ids:
        return "\n".join(f"[{t['tid']}] {t['speaker']}: {t['text']}" for t in turns)
    return "\n".join(f"{t['speaker']}: {t['text']}" for t in turns)


# ---------------------------------------------------------------- text
_ABBREV = re.compile(r"\b(Dr|Mr|Mrs|Ms|Prof|St|Jr|Sr|vs|approx|e\.g|i\.e|etc|No|Fig|mg|mL|q\.d|b\.i\.d|t\.i\.d)\.",
                     re.IGNORECASE)


def split_sentences(text: str) -> List[str]:
    """Deterministic splitter (no optional dependency), so data_out is identical on every machine.
    Abbreviations such as 'Dr.' are protected before splitting."""
    text = text.strip()
    if not text:
        return []
    protected = _ABBREV.sub(lambda m: m.group(0).replace(".", "․"), text)
    segs = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", protected)
    return [s.replace("․", ".").strip() for s in segs if s.strip()]


def norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def strip_bullet(line: str) -> str:
    return re.sub(r"^\s*(?:[-*+•▪◦]|\d+[.)])\s*", "", line).replace("**", "").strip()


def parse_json_loose(text: str):
    if text is None:
        return None
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for pat in (r"\{.*\}", r"\[.*\]"):
        m = re.search(pat, text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                continue
    return None


class Timer:
    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *a):
        self.seconds = time.perf_counter() - self.t0


def load_encounters(split: str) -> Dict[str, dict]:
    from config import DATA_DIR
    return {e["encounter_id"]: e for e in read_jsonl(DATA_DIR / f"encounters_{split}.jsonl")}


def load_statements(split: str, include_planted: bool = True, use_audit: bool = True) -> List[dict]:
    """Valid reference statements (minus boilerplate and audit rejects) + approved planted statements."""
    from config import DATA_DIR
    rows = [r for r in read_jsonl(DATA_DIR / f"statements_{split}.jsonl") if not r.get("exclude")]
    audit = DATA_DIR / f"audit_valid_{split}.csv"
    if use_audit and audit.exists():
        drop = {a["statement_id"] for a in read_csv(audit) if str(a.get("valid_ok", "")).strip() == "0"}
        fix = {a["statement_id"]: a["section_ok"] for a in read_csv(audit)
               if str(a.get("section_ok", "")).strip() in ("Assessment", "Plan")}
        rows = [r for r in rows if r["statement_id"] not in drop]
        for r in rows:
            r["section"] = fix.get(r["statement_id"], r["section"])
    if include_planted:
        rows += read_jsonl(DATA_DIR / f"planted_{split}.jsonl")
    return rows
