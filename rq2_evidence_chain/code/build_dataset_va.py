# blocks 0 + 4: verify-and-ask notes -> RQ2 input files and splits
"""Build the RQ2 statement sets from the Verify-and-Ask (RQ1) outputs instead of ACI-Bench reference notes.

Input  : verify_and_ask_pipeline/Stage23_pipeline/output/stage23_output.json  (201 cases)
         - conversation : the simulated intake conversation (block 0 in the diagram)
         - stage1_ap    : the Assessment / Plan written by the RQ1 note writer, untouched by RQ1 (block 4 input)
Output : the same file types build_dataset.py writes, so every other RQ2 script works unchanged:
         encounters_<split>.jsonl, statements_<split>.jsonl, audit_valid_<split>.csv, va_manifest.json

Splits (use a separate RQ2_DATA_DIR / RQ2_RUNS_DIR / RQ2_REPORT_DIR, see the bottom of this docstring):
  va_dev        RQ1 dev cases whose ACI-Bench source is NOT train      -> tuning (thresholds)
  va_test       RQ1 test cases whose ACI-Bench source is NOT train     -> reported results
  va_trainorig  cases built from ACI-Bench TRAIN encounters (both RQ1 splits). The verifier was trained on
                these patients, so they are run only to produce final notes, never scored.

Differences from build_dataset.py (ACI-Bench):
  * evidence = the simulated conversation. It contains no spoken diagnosis or plan (the intake only takes the
    history), so it is already "pre-A/P": turns_preap = turns and mask_ap.py is not needed.
  * statements = one per sentence of each A/P bullet; a short field label such as
    "Clinical problems or diagnoses:" is removed; placeholder lines such as
    "No explicit management or follow-up plan was documented" are excluded.
  * gold_label = "valid" for every statement, as for ACI reference statements; audit_valid_<split>.csv lets the
    team mark wrong ones (valid_ok = 0), exactly as before.

Usage (from rq2_section_aware/):
  export RQ2_DATA_DIR=data_out_va RQ2_RUNS_DIR=runs_va RQ2_REPORT_DIR=reports_va
  python build_dataset_va.py
  # defaults: --va-json ../verify_and_ask_pipeline/Stage23_pipeline/output/stage23_output.json
  #           --prepared ../verify_and_ask_pipeline/stage1_pipeline/stage1_output/prepared_dataset.json
Keep the three directories separate from the ACI-Bench run: feature caches are stored per encounter id, and
D2Nxxx would otherwise reuse features extracted from the ORIGINAL dialogue.
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

import config as C
from build_dataset import classify_free_sentence
from common import parse_aci_dialogue, read_csv, split_sentences, strip_bullet, write_csv, write_jsonl

PLACEHOLDER = re.compile(
    r"^\s*no (explicit |specific |clear )?(management |follow[- ]?up |treatment |diagnostic )*(or follow[- ]?up )?"
    r"(plan|plans|treatment|diagnos\w*|medications?)\b.*\b(was|were|is|are|has been|have been)\b.*"
    r"\b(documented|mentioned|discussed|established|provided|stated)\b"
    r"|\bnot (explicitly )?(documented|mentioned|discussed|established) in the conversation\b"
    r"|^\s*(none|n/?a|not applicable|not documented|unknown)\.?\s*$",
    re.IGNORECASE)
FIELD_LABEL = re.compile(r"^([A-Za-z][A-Za-z /&(),-]{2,80}):\s+(.+)$")


def ap_statements(case_id, ap):
    rows = []
    for section, key in (("Assessment", "assessment"), ("Plan", "plan")):
        kind = "A" if section == "Assessment" else "P"
        for raw in (ap.get(key) or "").splitlines():
            line = strip_bullet(raw.strip())
            if not line:
                continue
            m = FIELD_LABEL.match(line)
            if m and len(m.group(1).split()) <= 10:   # "Clinical problems or diagnoses: ..." -> keep the content
                line = m.group(2).strip()
            for sent in split_sentences(line):
                if len(sent.split()) < 2:
                    continue
                placeholder = bool(PLACEHOLDER.search(sent))
                if placeholder:
                    stype = "placeholder"
                else:
                    stype, _ = classify_free_sentence(sent, kind)
                rows.append(dict(text=sent, section=section, stmt_type=stype, exclude=placeholder))
    out = []
    for i, r in enumerate(rows, 1):
        out.append(dict(statement_id=f"{case_id}_V{i:02d}", encounter_id=case_id, claim=r["text"], text=r["text"],
                        stmt_type=r["stmt_type"], section=r["section"], problem="", source_header="va_stage1_ap",
                        origin="va_generated", gold_label="valid", error_type="", exclude=r["exclude"]))
    return out


def aci_origin():
    """encounter_id -> ACI-Bench split file it comes from (train / valid / test1 ...)."""
    origin = {}
    for name, fname in C.ACI_SPLITS.items():
        for r in read_csv(C.ACI_DIR / fname):
            origin[r["encounter_id"]] = name
    return origin


def reference_text(ref):
    return "\n\n".join(f"{k.upper()}\n{(ref.get(k) or '').strip()}" for k in ("subjective", "objective",
                                                                              "assessment", "plan"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--va-json", default=str(C.REPO / "rq1_verify_and_ask" / "Stage23_pipeline" / "output"
                                             / "stage23_output.json"))
    ap.add_argument("--prepared", default=str(C.REPO / "rq1_verify_and_ask" / "stage1_pipeline"
                                              / "stage1_output" / "prepared_dataset.json"))
    a = ap.parse_args()

    if C.DATA_DIR.resolve() == (C.ROOT / "data_out").resolve():
        raise SystemExit("Set RQ2_DATA_DIR (and RQ2_RUNS_DIR, RQ2_REPORT_DIR) to separate folders first, e.g.\n"
                         "  export RQ2_DATA_DIR=data_out_va RQ2_RUNS_DIR=runs_va RQ2_REPORT_DIR=reports_va")
    records = [r for r in json.loads(Path(a.va_json).read_text(encoding="utf-8"))["records"]
               if r.get("status") == "success"]
    refs = {r["case_id"]: r["reference_soap"]
            for r in json.loads(Path(a.prepared).read_text(encoding="utf-8"))["records"]}
    origin = aci_origin()

    buckets = {"va_dev": ([], []), "va_test": ([], []), "va_trainorig": ([], [])}
    manifest = []
    for r in records:
        cid = r["case_id"]
        src = origin.get(cid, "unknown")
        split = "va_trainorig" if src == "train" else ("va_dev" if r["split"] == "dev" else "va_test")
        turns = parse_aci_dialogue(r["conversation"])
        if not turns:
            raise SystemExit(f"{cid}: conversation has no 'Doctor:' / 'Patient:' turns")
        enc = dict(encounter_id=cid, dataset="simulated_intake", split=split, rq1_split=r["split"],
                   aci_source_split=src, in_verifier_training=src == "train",
                   turns=turns, turns_preap=[dict(t) for t in turns],
                   mask_log="not masked: the simulated intake conversation contains no spoken diagnosis or plan",
                   reference_note=reference_text(refs.get(cid, {})))
        stmts = ap_statements(cid, r["stage1_ap"])
        buckets[split][0].append(enc)
        buckets[split][1].extend(stmts)
        kept = [s for s in stmts if not s["exclude"]]
        manifest.append(dict(case_id=cid, rq2_split=split, rq1_split=r["split"], aci_source_split=src,
                             n_turns=len(turns), n_statements=len(kept),
                             n_assessment=sum(s["section"] == "Assessment" for s in kept),
                             n_plan=sum(s["section"] == "Plan" for s in kept),
                             n_placeholders=len(stmts) - len(kept)))

    C.DATA_DIR.mkdir(parents=True, exist_ok=True)
    for split, (encs, stmts) in buckets.items():
        write_jsonl(C.DATA_DIR / f"encounters_{split}.jsonl", encs)
        write_jsonl(C.DATA_DIR / f"statements_{split}.jsonl", stmts)
        write_csv(C.DATA_DIR / f"audit_valid_{split}.csv",
                  [dict(s, valid_ok="", section_ok="", annotator="", notes="") for s in stmts if not s["exclude"]],
                  ["statement_id", "encounter_id", "section", "stmt_type", "problem", "claim",
                   "valid_ok", "section_ok", "annotator", "notes"])
        kept = [s for s in stmts if not s["exclude"]]
        print(f"[{split}] encounters={len(encs)} statements={len(kept)} "
              f"(placeholders excluded: {len(stmts) - len(kept)})")
        print("   section:", dict(Counter(s["section"] for s in kept)))
        no_plan = [e["encounter_id"] for e in encs
                   if not any(s["encounter_id"] == e["encounter_id"] and s["section"] == "Plan" for s in kept)]
        print(f"   encounters with no Plan statement: {len(no_plan)}")
    (C.DATA_DIR / "va_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"wrote {C.DATA_DIR}/ (encounters, statements, audit sheets, va_manifest.json)")


if __name__ == "__main__":
    main()
