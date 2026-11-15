"""Build the RQ2 evaluation set from ACI-Bench (proposal E2 'valid set').

For each encounter in the chosen splits:
  encounters_<split>.jsonl : encounter_id, dataset, dialogue turns (T1..Tn), reference note
  statements_<split>.jsonl : one row per Assessment / Plan statement of the REFERENCE note,
                             gold_label = "valid" (the valid set); planted errors are added later by
                             plant_errors.py with gold_label = "unsupported".

Why the original ACI dialogue and not the simulated consultation: reference A/P statements rest on
exam findings and results that the doctor dictates in the original encounter. The simulated patient
cannot report them, so pairing reference A/P with simulated dialogues would put unsupported
statements into the valid set. (Generated A/P from the agentic pipeline is handled by build_e1.py.)

Usage:
  python build_dataset.py --splits dev test1           # dev = ACI valid (tuning), test1 = E2 test
  python build_dataset.py --splits dev test1 test2 test3   # more statements, more power
"""
import argparse
import re
from collections import Counter

import config as C
from common import parse_aci_dialogue, read_csv, split_sentences, strip_bullet, write_jsonl, write_csv

AP_HEADERS = {"ASSESSMENT AND PLAN": "AP", "ASSESSMENT": "A", "IMPRESSION": "A",
              "PLAN": "P", "INSTRUCTIONS": "P"}
FIELD_TYPES = [  # (prefix regex, stmt_type, section)
    (r"medical reasoning", "reasoning", "Assessment"),
    (r"(additional|diagnostic) testing|diagnostics?|labs?|imaging", "test", "Plan"),
    (r"medical treatment|treatment|medications?|surgical intervention|procedures?", "treatment", "Plan"),
    (r"specialist referrals?|referrals?", "referral", "Plan"),
    (r"patient education( and counseling)?|counseling|education", "education", "Plan"),
    (r"follow[ -]?up", "followup", "Plan"),
    (r"patient agreements?", "boilerplate", "Plan"),
]
BOILERPLATE = re.compile(r"understands and agrees|all questions were answered|agreed? with the (recommended|plan)|"
                         r"voiced understanding|questions were (answered|addressed)",
                         re.IGNORECASE)
PLAN_CUES = re.compile(
    r"\b(will|plan|recommend|prescrib|order|schedul|refer|follow[ -]?up|return|continue|start|increase|"
    r"decrease|discontinu|stop|taper|inject|physical therapy|surgery|advised|instructed|see (him|her|them) back|"
    r"obtain|check|repeat|monitor|counsel|educat|discussed)\w*", re.IGNORECASE)
TEST_CUES = re.compile(r"\b(x-?ray|mri|ct|ultrasound|echo\w*|ekg|ecg|lab\w*|blood work|panel|a1c|test\w*|"
                       r"biopsy|culture|scan|stress test|colonoscopy|urinalysis)\b", re.IGNORECASE)
TREAT_CUES = re.compile(r"\b(\d+\s?mg|prescri\w+|continue|start\w*|increase\w*|decrease\w*|inject\w*|"
                        r"physical therapy|surgery|medication|tablet|cream|inhaler|brace|splint|ice|rest)\b",
                        re.IGNORECASE)
SUMMARY_CUE = re.compile(r"\b\d{1,3}[- ]year[- ]old\b", re.IGNORECASE)


def find_sections(note: str):
    """Return [(header, kind, body)] for A/P-type sections, in note order."""
    lines = note.splitlines()
    idx = []
    for i, l in enumerate(lines):
        h = l.strip().rstrip(":").upper()
        if re.fullmatch(r"[A-Z][A-Z /&]{3,}", h) and len(h) <= 40:
            idx.append((i, h))
    out = []
    for j, (i, h) in enumerate(idx):
        end = idx[j + 1][0] if j + 1 < len(idx) else len(lines)
        if h in AP_HEADERS:
            out.append((h, AP_HEADERS[h], "\n".join(lines[i + 1:end])))
    return out


def classify_free_sentence(sent: str, kind: str):
    """Sentence without a 'Field:' prefix -> (stmt_type, section)."""
    if SUMMARY_CUE.search(sent) and kind in ("A", "AP"):
        return "summary", "Assessment"
    if kind == "A":
        return "reasoning", "Assessment"
    is_plan = kind == "P" or bool(PLAN_CUES.search(sent))
    if not is_plan:
        return "reasoning", "Assessment"
    if re.search(r"\brefer", sent, re.I):
        return "referral", "Plan"
    if re.search(r"follow[ -]?up|see (him|her|them) back|return in", sent, re.I):
        return "followup", "Plan"
    if TEST_CUES.search(sent):
        return "test", "Plan"
    if TREAT_CUES.search(sent):
        return "treatment", "Plan"
    return "plan_other", "Plan"


def is_problem_header(line: str, kind: str) -> bool:
    """'Upper respiratory infection.' / '• Impingement syndrome of left shoulder' / '1. Hypertension.'"""
    body = strip_bullet(line).rstrip(".:").strip()
    if not body or ":" in body or len(body.split()) > 9:
        return False
    if PLAN_CUES.search(body) or SUMMARY_CUE.search(body):
        return False
    return kind in ("A", "AP") and not re.search(r"\b(is|are|was|has|have|he|she|they|i|we)\b", body, re.I)


def extract_statements(enc_id: str, note: str):
    stmts, problem = [], ""
    for header, kind, body in find_sections(note):
        for raw in body.splitlines():
            line = raw.strip()
            if not line:
                continue
            if is_problem_header(line, kind):
                problem = strip_bullet(line).rstrip(".:").strip()
                stmts.append(dict(text=problem, stmt_type="diagnosis", section="Assessment",
                                  problem=problem, source_header=header))
                continue
            body_line = strip_bullet(line)
            stype, sect = None, None
            m = re.match(r"^([A-Za-z /-]{3,40}):\s*(.+)$", body_line)
            if m:
                for pat, t, s in FIELD_TYPES:
                    if re.fullmatch(pat, m.group(1).strip(), re.I):
                        stype, sect, body_line = t, s, m.group(2).strip()
                        break
            for sent in split_sentences(body_line):
                if len(sent.split()) < 3:
                    continue
                if stype in ("reasoning", "boilerplate"):
                    t, s = stype, sect
                elif stype:  # Plan field: keep the section, refine the type per sentence
                    t, s = classify_free_sentence(sent, "P")
                    t = stype if t == "plan_other" else t
                else:
                    t, s = classify_free_sentence(sent, kind)
                if BOILERPLATE.search(sent):
                    t = "boilerplate"
                stmts.append(dict(text=sent, stmt_type=t, section=s, problem=problem, source_header=header))
    rows = []
    for i, s in enumerate(stmts, 1):
        claim = s["text"] if (not s["problem"] or s["stmt_type"] in ("diagnosis", "summary")) \
            else f"Regarding {s['problem']}: {s['text']}"
        rows.append(dict(statement_id=f"{enc_id}_V{i:02d}", encounter_id=enc_id, claim=claim, **s,
                         origin="reference", gold_label="valid", error_type="",
                         exclude=s["stmt_type"] == "boilerplate"))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--splits", nargs="+", default=["dev", "test1"])
    args = ap.parse_args()
    for split in args.splits:
        rows = read_csv(C.ACI_DIR / C.ACI_SPLITS[split])
        encs, stmts = [], []
        for r in rows:
            turns = parse_aci_dialogue(r["dialogue"])
            encs.append(dict(encounter_id=r["encounter_id"], dataset=r["dataset"], split=split,
                             turns=turns, reference_note=r["note"]))
            stmts.extend(extract_statements(r["encounter_id"], r["note"]))
        write_jsonl(C.DATA_DIR / f"encounters_{split}.jsonl", encs)
        write_jsonl(C.DATA_DIR / f"statements_{split}.jsonl", stmts)
        # Audit sheet: two team members confirm each reference statement is actually supported by the
        # dialogue (+ general clinical knowledge). Statements marked invalid are dropped from the valid set.
        write_csv(C.DATA_DIR / f"audit_valid_{split}.csv",
                  [dict(s, valid_ok="", section_ok="", annotator="", notes="") for s in stmts if not s["exclude"]],
                  ["statement_id", "encounter_id", "section", "stmt_type", "problem", "claim",
                   "valid_ok", "section_ok", "annotator", "notes"])
        kept = [s for s in stmts if not s["exclude"]]
        print(f"[{split}] encounters={len(encs)} statements={len(kept)} (excluded {len(stmts) - len(kept)})")
        print("   section:", dict(Counter(s["section"] for s in kept)))
        print("   type   :", dict(Counter(s["stmt_type"] for s in kept)))
        empty = [e["encounter_id"] for e in encs if not any(s["encounter_id"] == e["encounter_id"] for s in kept)]
        if empty:
            print("   WARNING no A/P statements parsed for:", empty)


if __name__ == "__main__":
    main()
