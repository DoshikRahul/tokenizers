"""Run the integrated Stage 2-3 controller over the Stage 1 output (inference only).

Each case is checkpointed to output/cases/<case_id>.json so an interrupted run resumes.

  python run_stage23.py --split dev            # tune thresholds on dev
  python run_stage23.py --split test           # final run with frozen thresholds
  python run_stage23.py --limit 3 --no-ask     # quick smoke test
  python run_stage23.py --answers answers.json # optional {case_id: {"q1": "answer", ...}}
"""
import argparse
import json
import sys
import time

import config as C
from common import read_json, write_json


def write_final_note(res, directory):
    """Readable final note: the improved S/O, then the Stage 1 A/P exactly as generated."""
    so = res.get("stage3_so") or res["stage2_so"]
    ap = res["stage1_ap"]
    source = "Stage 3" if res.get("stage3_so") else "Stage 2"
    text = (f"# Final note - {res['case_id']}\n\n"
            f"S/O below is the {source} output. A/P is unchanged from Stage 1.\n\n"
            f"## Subjective\n\n{so['subjective']}\n\n## Objective\n\n{so['objective']}\n\n"
            f"## Assessment (unchanged)\n\n{ap['assessment']}\n\n## Plan (unchanged)\n\n{ap['plan']}\n")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{res['case_id']}.md").write_text(text, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage1-json", default=str(C.STAGE1_OUTPUT_JSON))
    ap.add_argument("--split", choices=["dev", "test", "all"], default="all")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--retry-errors", action="store_true")
    ap.add_argument("--no-ask", action="store_true")
    ap.add_argument("--reuse-stage2", action="store_true",
                    help="reuse saved results from output/stage2_only/cases instead of re-verifying")
    ap.add_argument("--stage2-only", action="store_true",
                    help="verification only (no omission/ask); writes to output/stage2_only/")
    ap.add_argument("--no-gpt2", action="store_true", help="append additions instead of perplexity placement")
    ap.add_argument("--answers", help="JSON file with recorded follow-up answers")
    args = ap.parse_args()

    stage1 = read_json(args.stage1_json)["records"]
    records = [r for r in stage1 if r["status"] == "success" and (args.split == "all" or r.get("split") == args.split)]
    if args.limit:
        records = records[: args.limit]
    if not records:
        sys.exit("No successful Stage 1 records selected.")
    answers = read_json(args.answers) if args.answers else {}

    if args.stage2_only:  # keep Stage-2-only results apart from full Stage 2-3 results
        base = C.OUTPUT_DIR / "stage2_only"
        C.CASES_DIR, C.UNSUPPORTED_DIR = base / "cases", base / "unsupported_claims"
        C.FINAL_NOTES_DIR = base / "final_notes"
        C.STAGE23_JSON = base / "stage2_output.json"

    C.CASES_DIR.mkdir(parents=True, exist_ok=True)
    C.UNSUPPORTED_DIR.mkdir(parents=True, exist_ok=True)
    from controller import Stage23Controller
    ctrl = Stage23Controller(enable_ask=not args.no_ask, use_gpt2_placement=not args.no_gpt2,
                             stage2_only=args.stage2_only)

    out = []
    try:
        for i, rec in enumerate(records, 1):
            path = C.CASES_DIR / f"{rec['case_id']}.json"
            if path.exists() and not args.overwrite:
                saved = read_json(path)
                if saved.get("status") != "error" or not args.retry_errors:
                    print(f"[{i}/{len(records)}] {rec['case_id']}: reusing saved")
                    out.append(saved)
                    continue
            print(f"[{i}/{len(records)}] {rec['case_id']}")
            t0 = time.time()
            if args.reuse_stage2 and not args.stage2_only:
                s2 = C.OUTPUT_DIR / "stage2_only" / "cases" / f"{rec['case_id']}.json"
                if not s2.exists():
                    sys.exit(f"--reuse-stage2: {s2} not found; run Stage 2 for this case first.")
                rec = {**rec, "_stage2": read_json(s2)}
            try:
                res = ctrl.run_case(rec, answers.get(rec["case_id"]))
                res["status"] = "success"
            except Exception as exc:
                res = {"case_id": rec["case_id"], "split": rec.get("split"), "status": "error",
                       "error": f"{type(exc).__name__}: {exc}"}
                print(f"[ERROR] {rec['case_id']}: {res['error']}", file=sys.stderr)
            res["seconds"] = round(time.time() - t0, 1)
            if res["status"] == "success" and "stage3_added" in res:
                kept = len(res["gaps"].get("gaps", []))
                print(f"    {res['seconds']}s | candidates flagged={res['stage3_stats']['num_flagged']} "
                      f"added={res['stage3_stats']['num_added']} | questions={kept}", flush=True)
            # evaluator-side only: keep conversation + reference with the record for the evaluation script
            if res["status"] == "success":  # integrity check: A/P must be identical to Stage 1's
                res["ap_unchanged"] = res.get("stage1_ap") == rec["stage1_ap"]
                if not res["ap_unchanged"]:
                    print(f"[WARN] {rec['case_id']}: A/P differs from Stage 1!", file=sys.stderr)
            res["conversation"] = rec["conversation"]
            res["reference_so"] = rec["reference_so"]
            write_json(path, res)
            if res["status"] == "success":
                write_json(C.UNSUPPORTED_DIR / f"{rec['case_id']}.json",
                           {"case_id": rec["case_id"], **res["unsupported_claims"]})
                write_final_note(res, C.FINAL_NOTES_DIR)
            out.append(res)
    except KeyboardInterrupt:
        print("\nInterrupted; finished cases are saved. Re-run to resume.")
    finally:
        if out:
            write_json(C.STAGE23_JSON, {
                "num_cases": len(out),
                "num_success": sum(r["status"] == "success" for r in out),
                "num_errors": sum(r["status"] == "error" for r in out),
                "records": out,
            })
            print(f"Saved {C.STAGE23_JSON}")
            from collections import Counter
            ok = [r for r in out if r["status"] == "success"]
            dec = Counter(a["decision"] for r in ok for a in r["stage2_audit"])
            claims = sum(v for k, v in dec.items() if k != "exempt")
            kept = sum(r["stage2_stats"]["num_kept"] for r in ok)
            print(f"\nStage 2 summary over {len(ok)} case(s): {dict(dec)}")
            if claims:
                print(f"Claims checked: {claims}; kept: {kept} ({kept / claims:.0%})")


if __name__ == "__main__":
    main()
