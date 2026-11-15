"""Shared SOAP parsing/cleaning helpers used by all Stage 1 scripts."""
import re

SECTIONS = ("subjective", "objective", "assessment", "plan")

# Matches "## Subjective", "### Subjective:", "**Subjective**", "**Subjective:**", "Subjective:".
_HEADING = r"^\s{0,3}(?:(#{1,6})\s+)?(?:\*\*|__)?%s(?:\*\*|__)?\s*:?\s*(?:\*\*|__)?\s*#*\s*$"
_ANY_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+\S")
_ANY_SECTION = re.compile(
    r"^\s{0,3}(?:#{1,6}\s+)?(?:\*\*|__)?(subjective|objective|assessment|plan)(?:\*\*|__)?\s*:?\s*(?:\*\*|__)?\s*#*\s*$",
    re.IGNORECASE,
)


def extract_section(markdown: str, heading: str) -> str:
    """Return the text under `heading` until the next SOAP heading or same/higher Markdown heading."""
    lines = markdown.splitlines()
    target = re.compile(_HEADING % re.escape(heading), re.IGNORECASE)
    start = level = None
    for i, line in enumerate(lines):
        m = target.match(line)
        if m:
            start, level = i + 1, len(m.group(1) or "") or 6
            break
    if start is None:
        return ""
    end = len(lines)
    for i in range(start, len(lines)):
        if _ANY_SECTION.match(lines[i]):
            end = i
            break
        m = _ANY_HEADING.match(lines[i])
        if m and len(m.group(1)) <= level:
            end = i
            break
    return "\n".join(lines[start:end]).strip()


def split_soap(markdown: str) -> dict:
    """Split a note into its four sections and report which were found."""
    sections = {name: extract_section(markdown, name) for name in SECTIONS}
    missing = [name for name, text in sections.items() if not text]
    return {"sections": sections, "missing": missing, "parse_ok": not missing}


def clean_conversation(markdown: str) -> str:
    """Turn the agent-pipeline consultation.md into plain 'Doctor:'/'Patient:' turns.

    Drops the title line (it contains the case id) and '## Turn N' headers, and
    renames the simulated 'Patient agent' speaker to 'Patient'.
    """
    turns = []
    for line in markdown.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^\*\*(Doctor|Patient agent|Patient):\*\*\s*(.*)$", line)
        if m:
            speaker = "Doctor" if m.group(1) == "Doctor" else "Patient"
            turns.append(f"{speaker}: {m.group(2).strip()}")
        elif turns:  # continuation of the previous turn
            turns[-1] += " " + line
        else:
            turns.append(line)
    return "\n".join(turns)
