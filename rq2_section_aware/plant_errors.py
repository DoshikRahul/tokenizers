"""Plant unsupported A/P statements (proposal E2 error types 5-6, plus one hard-negative type).

  unsupported_diagnosis   Assessment: plausible for the complaint, but no finding in the encounter supports it
  plan_without_evidence   Plan: plausible test / drug / referral with no indication in the encounter
  contradicted_inference  (extension) Assessment or Plan that a stated finding rules out
                          (e.g. 'pneumonia' when the chest x-ray was clear). Hard negative: the cited
                          features look relevant, so a verifier that only checks topical relevance passes it.

The generator should be a different model from the verifier (default: GEN_* = Qwen3-14B server).

Step 1  python plant_errors.py --split test1            -> data_out/planted_candidates_test1.csv
Step 2  two team members fill 'approved' (1/0) and fix wording if needed (edit 'claim')
Step 3  python plant_errors.py --split test1 --merge    -> data_out/planted_test1.jsonl (approved rows only)
        add --accept-all to merge without review (dev split / smoke tests only).
"""
import argparse
import random

import config as C
from common import norm, read_csv, read_jsonl, turns_to_text, write_csv, write_jsonl
from llm import GenLLM

ERROR_TYPES = {
    "unsupported_diagnosis": "Assessment",
    "plan_without_evidence": "Plan",
    "contradicted_inference": None,  # model chooses
}

SYSTEM = ("You construct evaluation data for a clinical-note verification study. You write single "
          "Assessment/Plan statements that LOOK like they belong in the note but are deliberately NOT "
          "justified by the encounter. Output JSON only.")

USER = """Encounter dialogue:
{dialogue}

Reference Assessment and Plan (these are the correct statements; do NOT copy or paraphrase them):
{ap}

Write exactly three new statements, in the same style as the reference (same problem names, same voice):

1. "unsupported_diagnosis": an Assessment statement naming a diagnosis or clinical conclusion that is
   plausible for this patient's complaints, but for which the dialogue gives NO supporting symptom, finding
   or result (and nothing that rules it out either).
2. "plan_without_evidence": a Plan statement (test, medication with dose, procedure or referral) that is
   plausible for this kind of visit but has NO indication anywhere in the dialogue.
3. "contradicted_inference": an Assessment or Plan statement that is directly ruled out by something stated
   in the dialogue (a negative finding, a normal result, an allergy, a stated preference). Quote that turn.

Rules: one sentence each; attach each to one of the problems above; never reuse a diagnosis, test or drug
already in the reference A/P; no obviously absurd content.

Return JSON:
{{"unsupported_diagnosis": {{"problem": "...", "claim": "..."}},
  "plan_without_evidence": {{"problem": "...", "claim": "..."}},
  "contradicted_inference": {{"problem": "...", "section": "Assessment|Plan", "claim": "...",
                             "contradicting_turn": "T.."}}}}"""


def generate(split, limit=None, seed=C.SEED):
    encs = read_jsonl(C.DATA_DIR / f"encounters_{split}.jsonl")
    stmts = read_jsonl(C.DATA_DIR / f"statements_{split}.jsonl")
    llm = GenLLM()
    rows = []
    for e in encs[:limit]:
        own = [s for s in stmts if s["encounter_id"] == e["encounter_id"] and not s["exclude"]]
        ap = "\n".join(f"- [{s['section']}] {s['claim']}" for s in own)
        out = llm.chat_json(SYSTEM, USER.format(dialogue=turns_to_text(e["turns"]), ap=ap),
                            temperature=0.7, max_tokens=900) or {}
        ref_norm = norm(" ".join(s["text"] for s in own))
        for etype, sect in ERROR_TYPES.items():
            item = out.get(etype) or {}
            claim = (item.get("claim") or "").strip()
            if not claim:
                print(f"  {e['encounter_id']}: no {etype}")
                continue
            section = sect or ("Plan" if str(item.get("section", "")).lower().startswith("p") else "Assessment")
            problem = (item.get("problem") or "").strip()
            auto_flag = "copied_from_reference" if norm(claim) in ref_norm else ""
            rows.append(dict(encounter_id=e["encounter_id"], error_type=etype, section=section, problem=problem,
                             claim=claim if not problem else f"Regarding {problem}: {claim}",
                             contradicting_turn=item.get("contradicting_turn", ""), auto_flag=auto_flag,
                             approved="", annotator="", notes=""))
        print(f"  {e['encounter_id']}: {sum(r['encounter_id'] == e['encounter_id'] for r in rows)} planted")
    path = C.DATA_DIR / f"planted_candidates_{split}.csv"
    write_csv(path, rows)
    print(f"wrote {len(rows)} candidates -> {path}. Review 'approved' before --merge.")


def merge(split, accept_all=False):
    rows = read_csv(C.DATA_DIR / f"planted_candidates_{split}.csv")
    out, counters = [], {}
    for r in rows:
        ok = accept_all and not r.get("auto_flag") or str(r.get("approved", "")).strip() in ("1", "y", "yes", "true")
        if not ok:
            continue
        k = counters[r["encounter_id"]] = counters.get(r["encounter_id"], 0) + 1
        out.append(dict(statement_id=f"{r['encounter_id']}_X{k:02d}", encounter_id=r["encounter_id"],
                        claim=r["claim"], text=r["claim"], stmt_type=r["error_type"], section=r["section"],
                        problem=r["problem"], source_header="planted", origin="planted",
                        gold_label="unsupported", error_type=r["error_type"], exclude=False,
                        contradicting_turn=r.get("contradicting_turn", "")))
    if not accept_all and not out:
        print("No approved rows. Fill the 'approved' column (1/0) or pass --accept-all.")
    write_jsonl(C.DATA_DIR / f"planted_{split}.jsonl", out)
    by = {}
    for o in out:
        by[o["error_type"]] = by.get(o["error_type"], 0) + 1
    print(f"merged {len(out)} planted statements: {by}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test1")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--accept-all", action="store_true")
    a = ap.parse_args()
    random.seed(C.SEED)
    merge(a.split, a.accept_all) if a.merge else generate(a.split, a.limit)
