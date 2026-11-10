"""Create the 'pre-A/P' evidence setting: the encounter with the doctor's spoken assessment and plan removed.

Why: in ACI-Bench the doctor dictates the assessment and plan aloud ("for your diabetes I want to increase
your metformin to 1000 mg twice daily"), so reference A/P statements are often literally entailed by the
full dialogue. In our system A/P is written AFTER the intake freeze from the collected evidence, so the
dialogue never contains the doctor's conclusions. The pre-A/P setting reproduces that: history, exam
findings, results and patient preferences stay; diagnoses, impressions, orders, prescriptions, referrals
and follow-up instructions spoken by the doctor are removed. Turn ids are NOT renumbered.

  python mask_ap.py --split dev
  python mask_ap.py --split test1
-> adds 'turns_preap' + 'mask_log' to encounters_<split>.jsonl, writes mask_audit_<split>.csv
   (two team members spot-check ~10 encounters; fix by editing the JSONL if needed).
"""
import argparse

import config as C
from common import read_jsonl, turns_to_text, write_csv, write_jsonl
from llm import GenLLM

SYSTEM = "You edit clinical encounter transcripts for an evaluation study. Output JSON only."
USER = """Transcript (turn ids in brackets):
{dialogue}

Find every DOCTOR turn that states a diagnosis, impression, assessment, differential, or any plan
(treatment, prescription, dose change, test or imaging order, referral, procedure, follow-up, instructions),
including voice-assistant orders such as "hey dragon, order ...".

For each such turn return either
  - "remove": the whole turn is assessment/plan talk, or
  - "keep_text": the turn mixes facts and conclusions; give the turn text with ONLY the conclusions removed,
    keeping history, examination findings, vital signs and test/imaging RESULTS verbatim.
Never edit patient turns. Never remove examination findings or results.

Return JSON: {{"edits": [{{"tid": "T57", "action": "remove"}}, {{"tid": "T40", "action": "keep_text", "keep_text": "..."}}]}}"""


WINDOW = 30  # turns per LLM call: keeps each JSON answer well under the server's 2048-token output cap


def mask(enc, llm):
    """Returns (new_turns, log) or (None, reason) if any window could not be parsed."""
    turns = enc["turns"]
    edits = {}
    for start in range(0, len(turns), WINDOW):
        window = turns[start:start + WINDOW]
        if not any(t["speaker"] == "Doctor" for t in window):
            continue
        out = llm.chat_json(SYSTEM, USER.format(dialogue=turns_to_text(window)), max_tokens=2048)
        if not isinstance(out, dict) or not isinstance(out.get("edits"), list):
            return None, f"unparseable LLM output for turns {window[0]['tid']}-{window[-1]['tid']}"
        ids = {t["tid"] for t in window}
        edits.update({e.get("tid"): e for e in out["edits"] if isinstance(e, dict) and e.get("tid") in ids})
    new, log = [], []
    for t in turns:
        e = edits.get(t["tid"])
        if not e or t["speaker"] != "Doctor":
            new.append(t)
            continue
        if e.get("action") == "keep_text" and (e.get("keep_text") or "").strip():
            new.append(dict(t, text=e["keep_text"].strip()))
            log.append(dict(tid=t["tid"], action="keep_text", original=t["text"], kept=e["keep_text"].strip()))
        else:
            log.append(dict(tid=t["tid"], action="remove", original=t["text"], kept=""))
    return new, log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", required=True)
    ap.add_argument("--redo", action="store_true")
    a = ap.parse_args()
    path = C.DATA_DIR / f"encounters_{a.split}.jsonl"
    encs, llm, audit, failed = read_jsonl(path), GenLLM(), [], []
    for e in encs:
        if "turns_preap" in e and not a.redo:
            continue
        new, log = mask(e, llm)
        if new is None:  # leave the encounter unmasked; run_rq2 --setting preap will refuse it
            print(f"  FAILED {e['encounter_id']}: {log} - rerun mask_ap.py")
            failed.append(e["encounter_id"])
            continue
        e["turns_preap"], e["mask_log"] = new, log
        print(f"  {e['encounter_id']}: {len(log)} doctor turns edited/removed")
        audit += [dict(encounter_id=e["encounter_id"], **m, correct="", notes="") for m in e["mask_log"]]
        write_jsonl(path, encs)  # checkpoint after each encounter
    if audit:
        write_csv(C.DATA_DIR / f"mask_audit_{a.split}.csv", audit)
    print("done ->", path, f"({len(failed)} failed: {failed})" if failed else "")


if __name__ == "__main__":
    main()
