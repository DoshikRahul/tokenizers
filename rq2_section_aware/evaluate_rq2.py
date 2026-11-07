"""Score RQ2 runs: P1 (valid-claim retention), P2 (unsupported A/P rejection P/R), S3 (reference ablation),
threshold tuning on dev, trade-off curves, paired statistics and the H2 verdict.

  python evaluate_rq2.py --split dev --tune          # pick thresholds per run on dev -> reports/thresholds.json
  python evaluate_rq2.py --split test1               # apply frozen thresholds, write reports/test1/*

Rejection = flag or delete. U1 is scored at its published uMedSum decision (and, as a diagnostic, at a
dev-tuned threshold on statement entailment: run name suffix '+tuned').
"""
import argparse
import re
from collections import defaultdict
from pathlib import Path

import config as C
from common import load_statements, read_json, read_jsonl, write_csv, write_json
from stats import bootstrap_ci, cluster_bootstrap_diff, holm, mcnemar_exact, roc_auc

THR_FILE = C.REPORT_DIR / "thresholds.json"


def split_agnostic(run):  # thresholds are keyed by run name, which does not contain the split
    return run


def load_runs(split):
    d = C.RUNS_DIR / split
    runs = {}
    for p in sorted(d.glob("*.jsonl")):
        if p.stem.startswith("chain_"):
            continue
        runs[p.stem] = {r["statement_id"]: r for r in read_jsonl(p)}
    return runs


def youden_threshold(recs, gold):
    """Threshold on p_reject maximising (recall on unsupported + retention on valid) - 1."""
    pts = sorted({round(r["p_reject"], 6) for r in recs.values()})
    cands = [0.0] + [(a + b) / 2 for a, b in zip(pts, pts[1:])] + [1.0 + 1e-9]
    best, best_j = 0.5, -1
    for t in cands:
        rec = [recs[s]["p_reject"] >= t for s in recs if gold[s]["gold_label"] == "unsupported"]
        ret = [recs[s]["p_reject"] < t for s in recs if gold[s]["gold_label"] == "valid"]
        if not rec or not ret:
            continue
        j = sum(rec) / len(rec) + sum(ret) / len(ret) - 1
        if j > best_j:
            best, best_j = t, j
    return best


def decisions(run, recs, thresholds):
    if run.endswith("+tuned"):
        base = run[:-6]
        t = thresholds.get(base + "+tuned", 0.5)
        return {s: r["p_reject"] >= t for s, r in recs.items()}
    if run.startswith("U1") or run not in thresholds:
        return {s: bool(r["reject"]) for s, r in recs.items()}
    t = thresholds[run]
    return {s: r["p_reject"] >= t for s, r in recs.items()}


def metrics(dec, recs, gold, ids):
    ids = [i for i in ids if i in dec]
    valid = [i for i in ids if gold[i]["gold_label"] == "valid"]
    uns = [i for i in ids if gold[i]["gold_label"] == "unsupported"]
    rej = [i for i in ids if dec[i]]
    tp = sum(gold[i]["gold_label"] == "unsupported" for i in rej)
    m = dict(n=len(ids), n_valid=len(valid), n_unsupported=len(uns),
             valid_retention=sum(not dec[i] for i in valid) / len(valid) if valid else None,
             reject_precision=tp / len(rej) if rej else None,
             reject_recall=tp / len(uns) if uns else None,
             flag_rate=len(rej) / len(ids) if ids else None,
             auc=roc_auc([recs[i]["p_reject"] for i in uns], [recs[i]["p_reject"] for i in valid]),
             sec_per_claim=sum(recs[i].get("seconds", 0) for i in ids) / len(ids) if ids else None)
    if m["reject_precision"] is not None and m["reject_recall"]:
        p, r = m["reject_precision"], m["reject_recall"]
        m["reject_f1"] = 2 * p * r / (p + r) if p + r else 0.0
    return m


def curve(run, recs, gold):
    rows = []
    for t in [i / 50 for i in range(51)]:
        v = [recs[s]["p_reject"] < t for s in recs if gold[s]["gold_label"] == "valid"]
        u = [recs[s]["p_reject"] >= t for s in recs if gold[s]["gold_label"] == "unsupported"]
        rows.append(dict(run=run, threshold=t, valid_retention=sum(v) / max(1, len(v)),
                         reject_recall=sum(u) / max(1, len(u))))
    return rows


def pick_primary(runs, setting):
    """Default run per condition for the main comparison: whole-dialogue U2, LLM linker for U3/U4."""
    out = {}
    for cond in ("U1", "U2", "U3", "U4"):
        cands = [r for r in runs if r.startswith(f"{cond}_{setting}") and "_top" not in r
                 and "link-retrieval" not in r and not r.endswith("+tuned")]
        if cands:
            out[cond] = sorted(cands, key=len)[0]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test1")
    ap.add_argument("--tune", action="store_true", help="tune thresholds on this split (use dev)")
    ap.add_argument("--setting", default="preap", choices=["preap", "full"])
    a = ap.parse_args()

    stmts = load_statements(a.split)
    gold = {s["statement_id"]: s for s in stmts}
    cluster = {s["statement_id"]: s["encounter_id"] for s in stmts}
    runs = {k: {s: r for s, r in v.items() if s in gold} for k, v in load_runs(a.split).items()}
    if not runs:
        raise SystemExit(f"no runs in {C.RUNS_DIR / a.split}")
    for k in [k for k in runs if k.startswith("U1")]:
        runs[k + "+tuned"] = runs[k]

    if a.tune:
        thr = {run: youden_threshold(recs, gold) for run, recs in runs.items()
               if not run.startswith("U1") or run.endswith("+tuned")}
        old = read_json(THR_FILE) if THR_FILE.exists() else {}
        old.update(thr)
        write_json(THR_FILE, old)
        print("thresholds (dev, Youden J):", {k: round(v, 3) for k, v in thr.items()})
    thresholds = read_json(THR_FILE) if THR_FILE.exists() else {}
    if not a.tune and not thresholds:
        print("WARNING: no dev thresholds found; U2-U4 use the default TAU_* decisions stored in the runs.")

    out_dir = C.REPORT_DIR / a.split
    table, curves, by_type = [], [], []
    decs = {}
    for run, recs in runs.items():
        dec = decs[run] = decisions(run, recs, thresholds)
        for section in ("all", "Assessment", "Plan"):
            ids = [i for i in recs if section == "all" or gold[i]["section"] == section]
            m = metrics(dec, recs, gold, ids)
            row = dict(run=run, section=section, **m)
            if section == "all":
                vals = {i: not dec[i] for i in ids if gold[i]["gold_label"] == "valid"}
                if vals:
                    row["retention_ci"] = bootstrap_ci(vals, cluster, C.N_BOOT, C.SEED)
                if run.startswith("U4"):
                    flags = [c.get("reference_found") for r in recs.values() for c in r.get("components", [])]
                    row["reference_coverage"] = sum(bool(f) for f in flags) / max(1, len(flags))
            table.append(row)
        for et in sorted({gold[i]["error_type"] for i in recs if gold[i]["error_type"]}):
            ids = [i for i in recs if gold[i]["error_type"] == et]
            by_type.append(dict(run=run, error_type=et, n=len(ids), recall=sum(dec[i] for i in ids) / len(ids)))
        if not run.endswith("+tuned"):
            curves += curve(run, recs, gold)

    # ---------------- paired comparisons (primary family) + H2
    prim = pick_primary(runs, a.setting)
    pairs = [(x, y) for x, y in [("U1", "U2"), ("U1", "U3"), ("U1", "U4"), ("U2", "U3"), ("U2", "U4"), ("U3", "U4")]
             if x in prim and y in prim]
    comps, pvals = [], {}
    for x, y in pairs:
        rx, ry = prim[x], prim[y]
        common = [i for i in runs[rx] if i in runs[ry]]
        v = [i for i in common if gold[i]["gold_label"] == "valid"]
        u = [i for i in common if gold[i]["gold_label"] == "unsupported"]
        ret_x, ret_y = {i: not decs[rx][i] for i in v}, {i: not decs[ry][i] for i in v}
        rec_x, rec_y = {i: decs[rx][i] for i in u}, {i: decs[ry][i] for i in u}
        d_ret = cluster_bootstrap_diff(ret_x, ret_y, cluster, C.N_BOOT, C.SEED)
        d_rec = cluster_bootstrap_diff(rec_x, rec_y, cluster, C.N_BOOT, C.SEED)
        mc_ret, mc_rec = mcnemar_exact(ret_x, ret_y), mcnemar_exact(rec_x, rec_y)
        pvals[f"{y}-{x} retention"], pvals[f"{y}-{x} recall"] = mc_ret["p"], mc_rec["p"]
        comps.append(dict(comparison=f"{y} vs {x}", run_a=rx, run_b=ry,
                          d_retention=d_ret, mcnemar_retention=mc_ret, d_recall=d_rec, mcnemar_recall=mc_rec))
    adj = holm(pvals)
    for c in comps:
        k = c["comparison"].replace(" vs ", "-")
        c["p_holm_retention"], c["p_holm_recall"] = adj.get(f"{k} retention"), adj.get(f"{k} recall")

    h2 = {}
    for ours in ("U3", "U4"):
        c = next((c for c in comps if c["comparison"] == f"{ours} vs U2"), None)
        if c:
            h2[ours] = dict(
                more_retention=c["d_retention"]["lo"] > 0,
                recall_noninferior=c["d_recall"]["lo"] > -C.H2_MARGIN,
                supported=c["d_retention"]["lo"] > 0 and c["d_recall"]["lo"] > -C.H2_MARGIN,
                note=f"retention diff CI [{c['d_retention']['lo']:.3f},{c['d_retention']['hi']:.3f}]; "
                     f"recall diff CI [{c['d_recall']['lo']:.3f},{c['d_recall']['hi']:.3f}] vs margin -{C.H2_MARGIN}")
    u1 = next((r for r in table if r["run"] == prim.get("U1") and r["section"] == "all"), None)
    if u1:
        h2["problem_demo_U1_rejects_valid"] = 1 - (u1["valid_retention"] or 0)

    # ---------------- S3: where do reference passages change the decision?
    s3 = []
    if "U3" in prim and "U4" in prim:
        for i in runs[prim["U4"]]:
            if i in runs[prim["U3"]] and decs[prim["U3"]][i] != decs[prim["U4"]][i]:
                r4 = runs[prim["U4"]][i]
                s3.append(dict(statement_id=i, gold=gold[i]["gold_label"], section=gold[i]["section"],
                               claim=gold[i]["claim"], U3_reject=decs[prim["U3"]][i], U4_reject=decs[prim["U4"]][i],
                               passages="; ".join(f"{p['title']}/{p['section']}" for c in r4.get("components", [])
                                                  for p in c.get("passages", []))))

    write_csv(out_dir / "metrics.csv", table)
    write_csv(out_dir / "recall_by_error_type.csv", by_type)
    write_csv(out_dir / "tradeoff_curves.csv", curves)
    write_csv(out_dir / "s3_decision_changes.csv", s3)
    write_json(out_dir / "summary.json", dict(split=a.split, setting=a.setting, primary_runs=prim,
                                               thresholds=thresholds, comparisons=comps, H2=h2))
    # ---------------- readable table
    lines = ["| run | section | retention | rej. precision | rej. recall | flag rate | AUC | s/claim |",
             "|---|---|---|---|---|---|---|---|"]
    f = lambda x: "-" if x is None else f"{x:.3f}"
    for r in table:
        lines.append(f"| {r['run']} | {r['section']} | {f(r['valid_retention'])} | {f(r['reject_precision'])} | "
                     f"{f(r['reject_recall'])} | {f(r['flag_rate'])} | {f(r['auc'])} | {f(r['sec_per_claim'])} |")
    (out_dir / "metrics.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print("\nH2:", h2)
    print("reports ->", out_dir)


if __name__ == "__main__":
    main()
