# block 12: simulated doctor sign-off
"""Block 12 (simulated doctor sign-off): turn the RQ2 run on the Verify-and-Ask notes into final notes.

For every case it combines
  * the verified S/O and the open questions from RQ1   (verify_and_ask_pipeline/.../output/cases/<case>.json)
  * each A/P statement's RQ2 record                    (runs/<split>/<run>.jsonl, written by run_rq2.py)
  * the flag threshold tuned on dev                    (reports/thresholds.json, written by evaluate_rq2.py --tune)
and applies the sign-off rule that stands in for the doctor:
  OK lines are kept; flagged lines are held back for doctor review (never deleted, never rewritten);
  open questions are passed on as pending items.

Only the REAL copy (the note's own A/P statements) is signed. The TEST copy (real + planted statements) is used
only for the "perfect doctor" numbers in signoff_summary.json: how many planted errors would still reach the
signed note (those RQ2 did not flag) and how many flags the doctor has to review.

Usage (same RQ2_* folders as the runs):
  python signoff.py --run U4_preap_ref3_link-llm_hf
Writes to ../rq2_on_verify_and_ask/ by default:
  doctor_notes/<case>.md    review version: S/O + every A/P line marked OK / FLAGGED with its evidence
  signed_notes/<case>.md    signed version: S/O + OK A/P lines only (reader 1; input to the patient summary)
  cases/<case>.json         everything about the case in one file
  index.csv                 one row per case
  signoff_summary.json      counts per split, incl. the perfect-doctor numbers
"""
import argparse
import csv
import json
from pathlib import Path

import config as C
from common import load_encounters, load_statements, read_json, read_jsonl, write_json

SPLITS = ("va_dev", "va_test", "va_trainorig")
SCORED = ("va_dev", "va_test")


def load_run(split, run):
    p = C.RUNS_DIR / split / f"{run}.jsonl"
    return {r["statement_id"]: r for r in read_jsonl(p)} if p.exists() else {}


def load_features(enc_id):
    p = C.RUNS_DIR / "features" / "preap" / f"{enc_id}.json"
    return {f["fid"]: f for f in read_json(p)["features"]} if p.exists() else {}


def judge(stmt, rec, tau):
    """-> status, score, evidence."""
    if rec is None or "p_reject" not in rec:
        return "not_checked", None, []
    status = "flagged" if rec["p_reject"] >= tau else "ok"
    return status, round(rec["p_reject"], 4), rec.get("components", [])


def evidence_lines(components, feats, status, tau):
    out = []
    for c in components:
        mark = " ← reason for flag" if status == "flagged" and c.get("p_broken", 0) >= tau else ""
        out.append(f"    - component: “{c['component']}” — P(chain broken) = {c.get('p_broken', 0):.2f}{mark}")
        for fid in c.get("feature_ids", []):
            f = feats.get(fid, {})
            turns = ", ".join(f.get("turns") or []) or "no turn cited"
            out.append(f"        - [{fid}] {f.get('text', '(feature not found)')} ({turns})")
        if not c.get("feature_ids"):
            out.append("        - no patient facts were linked")
        for p in c.get("passages", []):
            out.append(f"        - reference: MedlinePlus “{p.get('title', '')}” ({p.get('section', '')})")
    return out


def bullet_block(text):
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    return "\n".join(l if l.startswith(("*", "-", "•")) else f"* {l}" for l in lines) or "* (nothing documented)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="RQ2 run to sign off, e.g. U4_preap_ref3_link-llm_hf")
    ap.add_argument("--threshold", type=float, help="override the dev-tuned threshold")
    ap.add_argument("--va-cases", default=str(C.REPO / "verify_and_ask_pipeline" / "Stage23_pipeline" / "output"
                                              / "cases"))
    ap.add_argument("--out", default=str(C.REPO / "rq2_on_verify_and_ask"))
    a = ap.parse_args()

    thr_file = C.REPORT_DIR / "thresholds.json"
    tau = a.threshold
    if tau is None:
        thr = read_json(thr_file) if thr_file.exists() else {}
        if a.run not in thr:
            raise SystemExit(f"No dev-tuned threshold for {a.run} in {thr_file}. "
                             f"Run: python evaluate_rq2.py --split va_dev --tune  (or pass --threshold)")
        tau = thr[a.run]
    print(f"run {a.run}  threshold {tau:.4f}")

    out = Path(a.out)
    for d in ("doctor_notes", "signed_notes", "cases"):
        (out / d).mkdir(parents=True, exist_ok=True)
    va_dir = Path(a.va_cases)
    index, summary = [], {"run": a.run, "threshold": tau, "rule": "flagged = P(chain broken) >= threshold; "
                          "flagged lines held back for doctor review, OK lines signed", "splits": {}}

    for split in SPLITS:
        if not (C.DATA_DIR / f"encounters_{split}.jsonl").exists():
            continue
        encs = load_encounters(split)
        real = [s for s in load_statements(split, include_planted=False)]
        test_copy = load_statements(split, include_planted=True) if split in SCORED else real
        recs = load_run(split, a.run)
        if not recs:
            print(f"[{split}] no run file runs/{split}/{a.run}.jsonl - skipped")
            continue

        # ---------------- perfect-doctor numbers on the test copy (known answers)
        if split in SCORED:
            valid = [s for s in test_copy if s["gold_label"] == "valid" and s["statement_id"] in recs]
            planted = [s for s in test_copy if s["gold_label"] == "unsupported" and s["statement_id"] in recs]
            flag = {sid: r["p_reject"] >= tau for sid, r in recs.items() if "p_reject" in r}
            n_enc = len({s["encounter_id"] for s in valid + planted}) or 1
            reach = sum(not flag.get(s["statement_id"], False) for s in planted)
            summary["splits"][split] = dict(
                encounters=n_enc, valid_statements=len(valid), planted_statements=len(planted),
                valid_held_back=sum(flag.get(s["statement_id"], False) for s in valid),
                planted_flagged=len(planted) - reach,
                planted_reaching_signed_note=reach,
                planted_reaching_rate=round(reach / len(planted), 4) if planted else None,
                flags_per_note_test_copy=round(sum(flag.get(s["statement_id"], False)
                                                   for s in valid + planted) / n_enc, 3))

        # ---------------- real copy: one doctor note + one signed note per case
        by_enc = {}
        for s in real:
            by_enc.setdefault(s["encounter_id"], []).append(s)
        for enc_id, enc in sorted(encs.items()):
            case = json.loads((va_dir / f"{enc_id}.json").read_text(encoding="utf-8"))
            so = case["stage3_so"]
            gaps = [g for g in (case.get("gaps") or {}).get("gaps", [])]
            feats = load_features(enc_id)
            lines = []
            for s in by_enc.get(enc_id, []):
                status, score, comps = judge(s, recs.get(s["statement_id"]), tau)
                lines.append(dict(statement_id=s["statement_id"], section=s["section"], text=s["claim"],
                                  status=status, p_chain_broken=score, components=comps))
            held = [l for l in lines if l["status"] != "ok"]

            # doctor-facing review note
            md = [f"# {enc_id} — note for doctor review", "",
                  f"RQ2 run `{a.run}`, flag threshold {tau:.2f}. ✓ = facts justify the line; "
                  f"⚑ = flagged for review (kept in this view, held back from the signed note).", "",
                  "## Subjective (verified by RQ1)", bullet_block(so.get("subjective")), "",
                  "## Objective (verified by RQ1)", bullet_block(so.get("objective")), ""]
            for sect in ("Assessment", "Plan"):
                md.append(f"## {sect} (checked by RQ2)")
                sl = [l for l in lines if l["section"] == sect]
                if not sl:
                    md.append("* (no statements)")
                for l in sl:
                    tag = {"ok": "✓", "flagged": "⚑ FLAGGED", "not_checked": "⚑ NOT CHECKED"}[l["status"]]
                    sc = f" — P(chain broken) = {l['p_chain_broken']:.2f}" if l["p_chain_broken"] is not None else ""
                    md.append(f"* {tag} {l['text']}{sc}")
                    md.extend(evidence_lines(l["components"], feats, l["status"], tau))
                md.append("")
            md.append("## Open questions from RQ1 (not answered)")
            md.extend([f"* [{g.get('category', '')}] {g.get('question', '')}" for g in gaps] or ["* none"])
            (out / "doctor_notes" / f"{enc_id}.md").write_text("\n".join(md) + "\n", encoding="utf-8")

            # signed note (reader 1)
            signed = {"subjective": so.get("subjective", ""), "objective": so.get("objective", ""),
                      "assessment": [l["text"] for l in lines if l["section"] == "Assessment" and l["status"] == "ok"],
                      "plan": [l["text"] for l in lines if l["section"] == "Plan" and l["status"] == "ok"]}
            sm = [f"# {enc_id} — signed SOAP note", "",
                  "## Subjective", bullet_block(signed["subjective"]), "",
                  "## Objective", bullet_block(signed["objective"]), "",
                  "## Assessment", "\n".join(f"* {t}" for t in signed["assessment"]) or "* (none signed)", "",
                  "## Plan", "\n".join(f"* {t}" for t in signed["plan"]) or "* (none signed)", "",
                  f"_{len(held)} A/P line(s) held back for doctor review; {len(gaps)} open question(s) pending._"]
            (out / "signed_notes" / f"{enc_id}.md").write_text("\n".join(sm) + "\n", encoding="utf-8")

            write_json(out / "cases" / f"{enc_id}.json", dict(
                case_id=enc_id, rq2_split=split, rq1_split=enc.get("rq1_split"),
                aci_source_split=enc.get("aci_source_split"), scored=split in SCORED,
                rq2_run=a.run, threshold=tau, so=so, open_questions=gaps, ap_lines=lines,
                signed_note=signed, conversation_turns=enc["turns"]))
            index.append(dict(case_id=enc_id, rq2_split=split, rq1_split=enc.get("rq1_split"),
                              aci_source_split=enc.get("aci_source_split"), scored=split in SCORED,
                              n_assessment=sum(l["section"] == "Assessment" for l in lines),
                              n_plan=sum(l["section"] == "Plan" for l in lines),
                              n_flagged=sum(l["status"] == "flagged" for l in lines),
                              n_not_checked=sum(l["status"] == "not_checked" for l in lines),
                              n_signed_ap=len(signed["assessment"]) + len(signed["plan"]),
                              n_open_questions=len(gaps),
                              n_open_subjective=sum(g.get("category") == "subjective" for g in gaps),
                              n_open_objective=sum(g.get("category") == "objective" for g in gaps)))
        done = [i for i in index if i["rq2_split"] == split]
        summary["splits"].setdefault(split, {}).update(
            cases=len(done), real_ap_lines=sum(i["n_assessment"] + i["n_plan"] for i in done),
            real_flagged=sum(i["n_flagged"] for i in done), real_not_checked=sum(i["n_not_checked"] for i in done),
            flags_per_note_real=round(sum(i["n_flagged"] for i in done) / max(len(done), 1), 3))
        print(f"[{split}] {len(done)} cases signed")

    with open(out / "index.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(index[0].keys()))
        w.writeheader()
        w.writerows(index)
    write_json(out / "signoff_summary.json", summary)
    print(json.dumps(summary, indent=1))
    print(f"wrote {out}/")


if __name__ == "__main__":
    main()
