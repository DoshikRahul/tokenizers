"""
Side-by-side comparison: uMedSum (baseline B3) vs Verify-and-Ask (ours) on the same split, same metrics.

Reads what evaluate.py already produced for each system (results_<split>.json plus its per-case caches),
so no model is re-run. Writes:
  comparison_<split>.md / .json    aggregate table (every metric, all stages of both systems)
  paired_tests_<split>.csv         per-metric paired test on the final notes (case by case)

Paired tests use the cases both systems completed. For each metric: mean of each system, mean difference
(ours - uMedSum), 95% bootstrap CI of the difference (10k resamples, seed 42) and the Wilcoxon
signed-rank p-value.

  python compare_results.py --split test
"""
import argparse
import csv
import json
import random
from pathlib import Path
from statistics import mean

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
NLI_TAG = "DeBERTa-v3-large-mnli-fever-anli-ling-wanli"
TE, TA, TCONTRA = 0.90, 0.50, 0.50  # evaluate.py defaults (config.py)
STAGES = {"A_stage1": "stage1_so", "B_verified": "stage2_so", "C_final": "stage3_so"}

# Direction: +1 higher is better, -1 lower is better, 0 informational.
DIRECTION = {
    "unsupported_claim_rate": -1, "contradiction_rate": -1, "uncertain_rate": -1,
    "unsupported_addition_rate": -1, "duplicate_addition_rate": -1, "question_redundancy_rate": -1,
    "num_claims": 0, "num_genuine_omissions": 0, "num_added": 0, "questions_kept": 0,
}


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def so_text(so):
    return "\n".join(x for x in ((so.get("subjective") or "").strip(), (so.get("objective") or "").strip()) if x)


# ------------------------------------------------------------------ per-case metrics
def per_case(records, eval_dir, system_key):
    """case_id -> {metric: value} for one stage of one system, from records + evaluate.py caches."""
    from rouge_score import rouge_scorer
    scorer = rouge_scorer.RougeScorer(["rouge1", "rouge2", "rougeLsum"], use_stemmer=True)
    stage = STAGES[system_key]
    g = eval_dir / f"grounding_cache_{NLI_TAG}.json"
    f = eval_dir / f"fact_scores_cache_{NLI_TAG}.json"
    facts_p = eval_dir / "reference_facts.json"
    gcache = load(g) if g.exists() else {}
    fcache = load(f) if f.exists() else {}
    facts = load(facts_p) if facts_p.exists() else {}
    out = {}
    for r in records:
        cid, m = r["case_id"], {}
        for prefix, fn in (("so_", so_text), ("subj_", lambda x: (x.get("subjective") or "").strip())):
            s = scorer.score(fn(r["reference_so"]), fn(r[stage]))
            m[prefix + "rouge1_f"] = s["rouge1"].fmeasure
            m[prefix + "rouge2_f"] = s["rouge2"].fmeasure
            m[prefix + "rougeLsum_f"] = s["rougeLsum"].fmeasure
        rows = gcache.get(f"{cid}|{system_key}|v2")
        if rows:
            labels = ["supported" if x["entailment"] >= TE else "contradicted" if x["contradiction"] >= TCONTRA
                      else "uncertain" if x["entailment"] >= TA else "unsupported" for x in rows]
            m["supported_rate"] = labels.count("supported") / len(labels)
            m["unsupported_claim_rate"] = (labels.count("unsupported") + labels.count("contradicted")) / len(labels)
            m["num_claims"] = len(labels)
        fc, cf = fcache.get(cid), facts.get(cid, [])
        if fc and cf and system_key in fc.get("represented", {}):
            rep = fc["represented"][system_key]
            m["atomic_fact_recall"] = sum(rep) / len(cf)
            crit = [i for i, x in enumerate(cf) if x["critical"]]
            if crit:
                m["critical_fact_recall"] = sum(rep[i] for i in crit) / len(crit)
            rec = [i for i in range(len(cf)) if fc["recoverable"][i]]
            if rec:
                m["recall_of_recoverable_facts"] = sum(rep[i] for i in rec) / len(rec)
        out[cid] = m
    return out


def bootstrap_ci(diffs, n=10000, seed=42):
    rnd = random.Random(seed)
    k = len(diffs)
    means = sorted(mean(rnd.choices(diffs, k=k)) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def wilcoxon_p(diffs):
    try:
        from scipy.stats import wilcoxon
        if all(abs(d) < 1e-12 for d in diffs):
            return 1.0
        return float(wilcoxon(diffs, zero_method="wilcox").pvalue)
    except Exception as exc:
        return f"n/a ({type(exc).__name__})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "test", "all"], default="test")
    ap.add_argument("--umedsum-json", default=str(HERE / "output" / "umedsum_output.json"))
    ap.add_argument("--umedsum-eval-dir", default=str(HERE / "output" / "evaluation"))
    ap.add_argument("--ours-json", default=str(REPO / "verify_and_ask_pipeline" / "Stage23_pipeline" / "output" / "stage23_output.json"))
    ap.add_argument("--ours-eval-dir", default=str(REPO / "verify_and_ask_pipeline" / "Stage23_pipeline" / "output" / "evaluation"))
    ap.add_argument("--out-dir", default=str(HERE / "output" / "comparison"))
    args = ap.parse_args()

    um_eval, ours_eval, out_dir = Path(args.umedsum_eval_dir), Path(args.ours_eval_dir), Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    um_res = load(um_eval / f"results_{args.split}.json")
    ours_res = load(ours_eval / f"results_{args.split}.json")

    # ---------------- aggregate table ----------------
    cols = [("uMedSum S1 (gen)", um_res, "A_stage1"), ("uMedSum S2 (RTB-TS)", um_res, "B_verified"),
            ("uMedSum S3 final", um_res, "C_final"), ("Ours A (Stage 1)", ours_res, "A_stage1"),
            ("Ours B (verified)", ours_res, "B_verified"), ("Ours C final", ours_res, "C_final")]
    metric_names = []
    for _, res, s in cols:
        for k in res["per_system"].get(s, {}):
            if k not in metric_names:
                metric_names.append(k)
    lines = [f"# uMedSum vs Verify-and-Ask - {args.split} split",
             f"uMedSum cases: {um_res['num_cases']} | Verify-and-Ask cases: {ours_res['num_cases']} | "
             f"eval NLI: {um_res.get('eval_nli_model')} / {ours_res.get('eval_nli_model')}",
             "S/O only; A/P is passed through unchanged in both systems and is not scored.", "",
             "| metric | " + " | ".join(c[0] for c in cols) + " | better |",
             "|---|" + "---|" * (len(cols) + 1)]
    for k in metric_names:
        vals = [res["per_system"].get(s, {}).get(k, "") for _, res, s in cols]
        d = DIRECTION.get(k, 1)
        um_v, our_v = vals[2], vals[5]
        better = ""
        if d and isinstance(um_v, (int, float)) and isinstance(our_v, (int, float)) and um_v != our_v:
            better = "ours" if (our_v - um_v) * d > 0 else "uMedSum"
        lines.append(f"| {k} | " + " | ".join(str(v) for v in vals) + f" | {better} |")
    lines += ["", "## Task / integrity metrics (final systems)", "", "| metric | uMedSum | Ours |", "|---|---|---|"]
    tkeys = list(dict.fromkeys(list(um_res["task_metrics"]) + list(ours_res["task_metrics"])))
    for k in tkeys:
        lines.append(f"| {k} | {um_res['task_metrics'].get(k, '')} | {ours_res['task_metrics'].get(k, '')} |")

    # ---------------- paired tests on final notes ----------------
    def recs(p):
        return {r["case_id"]: r for r in load(p)["records"]
                if r.get("status") == "success" and (args.split == "all" or r.get("split") == args.split)}
    um_recs, our_recs = recs(args.umedsum_json), recs(args.ours_json)
    common = sorted(set(um_recs) & set(our_recs))
    test_rows = []
    if common:
        um_pc = per_case([um_recs[c] for c in common], um_eval, "C_final")
        our_pc = per_case([our_recs[c] for c in common], ours_eval, "C_final")
        keys = ["subj_rouge1_f", "subj_rouge2_f", "subj_rougeLsum_f", "so_rouge1_f", "so_rouge2_f", "so_rougeLsum_f",
                "supported_rate", "unsupported_claim_rate", "atomic_fact_recall", "critical_fact_recall",
                "recall_of_recoverable_facts"]
        for k in keys:
            pairs = [(um_pc[c][k], our_pc[c][k]) for c in common if k in um_pc[c] and k in our_pc[c]]
            if len(pairs) < 5:
                continue
            diffs = [o - u for u, o in pairs]
            lo, hi = bootstrap_ci(diffs)
            d = DIRECTION.get(k, 1)
            test_rows.append({"metric": k, "n_cases": len(pairs),
                              "uMedSum_mean": round(mean(u for u, _ in pairs), 4),
                              "ours_mean": round(mean(o for _, o in pairs), 4),
                              "diff_ours_minus_umedsum": round(mean(diffs), 4),
                              "ci95_low": round(lo, 4), "ci95_high": round(hi, 4),
                              "wilcoxon_p": wilcoxon_p(diffs),
                              "ours_wins": sum(1 for x in diffs if x * d > 0),
                              "ties": sum(1 for x in diffs if x == 0),
                              "umedsum_wins": sum(1 for x in diffs if x * d < 0),
                              "higher_is_better": d > 0})
        with open(out_dir / f"paired_tests_{args.split}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(test_rows[0].keys()) if test_rows else ["metric"])
            w.writeheader()
            w.writerows(test_rows)
        lines += ["", f"## Paired comparison of final notes ({len(common)} shared cases)", "",
                  "| metric | uMedSum | ours | diff (ours-uMedSum) | 95% CI | Wilcoxon p | ours/tie/uMedSum wins |",
                  "|---|---|---|---|---|---|---|"]
        for t in test_rows:
            p = t["wilcoxon_p"]
            p = f"{p:.2g}" if isinstance(p, float) else p
            lines.append(f"| {t['metric']} | {t['uMedSum_mean']} | {t['ours_mean']} | {t['diff_ours_minus_umedsum']:+} | "
                         f"[{t['ci95_low']:+}, {t['ci95_high']:+}] | {p} | {t['ours_wins']}/{t['ties']}/{t['umedsum_wins']} |")
        lines += ["", "Grounding and fact-recall per-case values come from each system's own evaluate.py caches. "
                  "For a strictly matched comparison, both systems should be scored in the same environment "
                  "(see the optional re-scoring cell in the notebook)."]
    else:
        lines += ["", f"No shared successful cases in '{args.split}' between the two output files, so no paired tests. "
                  "(The repo's Verify-and-Ask stage23_output.json holds the 88 test cases only.)"]

    md = "\n".join(lines) + "\n"
    (out_dir / f"comparison_{args.split}.md").write_text(md, encoding="utf-8")
    (out_dir / f"comparison_{args.split}.json").write_text(
        json.dumps({"split": args.split, "umedsum": um_res, "ours": ours_res, "paired_tests": test_rows,
                    "shared_cases": common}, indent=2), encoding="utf-8")
    print(md)
    print("Saved to", out_dir)


if __name__ == "__main__":
    main()
