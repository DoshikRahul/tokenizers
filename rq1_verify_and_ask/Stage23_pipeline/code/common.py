"""Small shared helpers: text splitting, dialogue parsing, bullet handling, JSON IO."""
import json
import re
from pathlib import Path
from typing import List, Tuple

_PLACEHOLDER_RE = re.compile(
    r"\b(not (specified|documented|mentioned|stated|available|provided|discussed|reported)"
    r"|no objective clinical|none documented|no .{0,40} (was|were) documented)\b",
    re.IGNORECASE,
)
_QUESTION_START = re.compile(
    r"^(what|when|where|why|who|how|which|do|does|did|are|is|was|were|can|could|would|will|have|has|any)\b",
    re.IGNORECASE,
)


def split_sentences(text: str) -> List[str]:
    """Sentence split with pysbd when available, otherwise a regex fallback."""
    text = text.strip()
    if not text:
        return []
    try:
        import pysbd
        segs = pysbd.Segmenter(language="en", clean=False).segment(text)
    except ImportError:
        segs = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
    return [s.strip() for s in segs if s.strip()]


def parse_turns(dialogue: str) -> List[Tuple[str, str]]:
    """'Doctor: ...' / 'Patient: ...' lines -> [(speaker, text)]."""
    turns = []
    for line in dialogue.splitlines():
        m = re.match(r"^\s*(Doctor|Patient)\s*:\s*(.*)$", line)
        if m:
            turns.append((m.group(1), m.group(2).strip()))
        elif line.strip() and turns:
            turns[-1] = (turns[-1][0], turns[-1][1] + " " + line.strip())
    return turns


def is_question(sentence: str) -> bool:
    s = sentence.strip()
    return s.endswith("?")


def strip_bullet(line: str) -> Tuple[str, str]:
    """Return (marker, body) where marker keeps indentation and the bullet symbol."""
    m = re.match(r"^(\s*(?:[-*+•]|\d+[.)])?\s*)(.*)$", line)
    body = m.group(2).replace("**", "").replace("__", "").strip()
    return m.group(1), body


def is_placeholder(sentence: str) -> bool:
    """'Not specified' / 'No objective ... documented' statements describe absence, not claims."""
    return bool(_PLACEHOLDER_RE.search(sentence)) and len(sentence.split()) <= 45


def norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def so_to_text(so: dict) -> str:
    """Subjective/Objective dict -> one text block (used for scoring and for premise text)."""
    parts = []
    for key in ("subjective", "objective"):
        parts.append(f"{key.capitalize()}:\n{(so.get(key) or '').strip()}")
    return "\n\n".join(parts).strip()


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
