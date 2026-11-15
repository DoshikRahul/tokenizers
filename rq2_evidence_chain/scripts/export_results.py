# collect every block's results into CSV / JSON
"""Collect everything RQ2 produced on the Verify-and-Ask notes into a few CSV / JSON files.

rq2_results/
  blocks/b04_statements.csv      one row per A/P statement (real + planted; filler lines marked excluded)
  blocks/b05_components.csv      one row per piece after the claim splitter
  blocks/b06_facts.csv           one row per patient fact found by the fact collector
  blocks/b07_fact_checks.csv     one row per fact: P(supported) in its cited turns, kept or dropped
  blocks/b08_links.csv           one row per piece: the facts the linker picked
  blocks/b09_references.csv      one row per piece (U4): MedlinePlus passages and their closeness
  blocks/b10_chain_scores.csv    one row per piece: P(chain broken) without (U3) and with (U4) passages
  blocks/b11_flags.csv           one row per statement: score and flag for every condition (U1..U4)
  blocks/b12_signoff.csv         one row per case: A/P lines, flagged, signed, open questions
  blocks/b13_summary_drafts.csv  one row per summary sentence as written (verified-note draft + H3 control)
  blocks/b14_summary_checks.csv  one row per sentence: checked against the signed note and the conversation
  metrics.json                   every number, grouped by block
  combined.json                  one entry per case with everything joined

Only the scored splits (va_dev, va_test) are exported.
  python export_results.py --final ../rq2_on_verify_and_ask --out ../rq2_results [--train-info <json>]
"""
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

import config as C
from common import load_encounters, load_statements, read_json, read_jsonl

SPLITS = ("va_dev", "va_test")
CONDS = ("U1", "U2", "U3", "U4")


def write_csv(path, rows, cols=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = cols or (list(rows[0].keys()) if rows else ["empty"])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def avg(xs):
    xs = [x for x in xs if x is not None]
    return round(mean(xs), 4) if xs else None


def share(n, d):
    return round(n / d, 4) if d else None


def find_runs(split):
    """condition -> run name, primary runs only (whole dialogue, LLM linker, pre-A/P)."""
    out = {}
    for p in sorted((C.RUNS_DIR / split).glob("U*_preap*.jsonl")):
        name = p.stem
        cond = name[:2]
        if "_top" in name or "link-retrieval" in name or cond not in CONDS:
            continue
        out.setdefault(cond, name)
    return out


def read_metrics_csv(path):
    if not path.exists():
        return []
    rows = []
    for r in csv.DictReader(open(path, encoding="utf-8")):
        rows.append({k: (float(v) if v not in ("", None) and k not in ("run", "section", "error_type", "retention_ci")
                         else v) for k, v in r.items()})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", default=str(C.REPO / "rq2_on_verify_and_ask"))
    ap.add_argument("--out", default=str(C.REPO / "rq2_results"))
    ap.add_argument("--train-info", help="JSON with verifier training info (written by the notebook)")
    a = ap.parse_args()
    final, out = Path(a.final), Path(a.out)
    blocks = out / "blocks"
    thr = read_json(C.REPORT_DIR / "thresholds.json") if (C.REPORT_DIR / "thresholds.json").exists() else {}

    rows = {k: [] for k in ("b04", "b05", "b06", "b07", "b08", "b09", "b10", "b11", "b12", "b13", "b14")}
    combined = {}
    runs_used = {}
    for split in SPLITS:
        if not (C.DATA_DIR / f"encounters_{split}.jsonl").exists():
            continue
        encs = load_encounters(split)
        runs = find_runs(split)
        runs_used[split] = runs
        recs = {c: {r["statement_id"]: r for r in read_jsonl(C.RUNS_DIR / split / f"{n}.jsonl")}
                for c, n in runs.items()}
        stmts = load_statements(split, include_planted=True)
        all_real = read_jsonl(C.DATA_DIR / f"statements_{split}.jsonl")   # incl. excluded filler lines
        comps = {r["statement_id"]: r["components"] for r in read_jsonl(C.RUNS_DIR / split / "chain_components.jsonl")} \
            if (C.RUNS_DIR / split / "chain_components.jsonl").exists() else {}
        links = {r["statement_id"]: r["feature_ids"] for r in read_jsonl(C.RUNS_DIR / split / "chain_links_preap.jsonl")} \
            if (C.RUNS_DIR / split / "chain_links_preap.jsonl").exists() else {}

        # ---- block 4: statements (real incl. excluded filler + planted)
        kept_ids = {s["statement_id"] for s in stmts}
        for s in all_real + [s for s in stmts if s.get("origin") == "planted"]:
            rows["b04"].append(dict(statement_id=s["statement_id"], case_id=s["encounter_id"], split=split,
                                    section=s["section"], stmt_type=s.get("stmt_type", ""),
                                    origin="planted" if s.get("origin") == "planted" else "real",
                                    gold_label=s["gold_label"], error_type=s.get("error_type", ""),
                                    excluded=int(s["statement_id"] not in kept_ids), text=s["claim"]))
        # ---- blocks 6-7: facts
        for eid in encs:
            p = C.RUNS_DIR / "features" / "preap" / f"{eid}.json"
            feats = read_json(p)["features"] if p.exists() else []
            for f in feats:
                rows["b06"].append(dict(case_id=eid, split=split, fact_id=f["fid"], category=f.get("category", ""),
                                        turns=",".join(f.get("turns") or []), text=f["text"]))
                rows["b07"].append(dict(case_id=eid, split=split, fact_id=f["fid"],
                                        p_supported=f.get("ground_p"), kept=int(bool(f.get("grounded", True)))))
        # ---- blocks 5, 8, 9, 10, 11 per statement
        for s in stmts:
            sid, eid = s["statement_id"], s["encounter_id"]
            cl = comps.get(sid, [])
            u3 = (recs.get("U3", {}).get(sid) or {}).get("components", [])
            u4 = (recs.get("U4", {}).get(sid) or {}).get("components", [])
            for i, c in enumerate(cl):
                rows["b05"].append(dict(statement_id=sid, case_id=eid, split=split, component_index=i,
                                        n_components=len(cl), component=c))
                ids = links.get(f"{sid}#{i}#llm", [])
                rows["b08"].append(dict(statement_id=sid, case_id=eid, split=split, component_index=i,
                                        n_linked=len(ids), linked_fact_ids=",".join(ids)))
                c4 = u4[i] if i < len(u4) else {}
                ps = c4.get("passages", [])
                if c4:
                    rows["b09"].append(dict(statement_id=sid, case_id=eid, split=split, component_index=i,
                                            reference_found=int(bool(c4.get("reference_found"))),
                                            n_passages=len(ps), titles=" | ".join(p.get("title", "") for p in ps),
                                            sections=" | ".join(p.get("section", "") for p in ps),
                                            closeness=" | ".join(str(p.get("cos", "")) for p in ps)))
                c3 = u3[i] if i < len(u3) else {}
                rows["b10"].append(dict(statement_id=sid, case_id=eid, split=split, component_index=i,
                                        gold_label=s["gold_label"], p_broken_U3=c3.get("p_broken"),
                                        p_broken_U4=c4.get("p_broken")))
            flag_row = dict(statement_id=sid, case_id=eid, split=split, section=s["section"],
                            origin="planted" if s.get("origin") == "planted" else "real",
                            gold_label=s["gold_label"], error_type=s.get("error_type", ""), text=s["claim"])
            for c in CONDS:
                r = recs.get(c, {}).get(sid)
                run = runs.get(c)
                if not r or "p_reject" not in r:
                    flag_row[f"score_{c}"] = flag_row[f"flag_{c}"] = None
                    continue
                flag_row[f"score_{c}"] = round(r["p_reject"], 4)
                if c == "U1":   # published uMedSum decision (thresholds from the paper)
                    flag_row["flag_U1"] = int(bool(r["reject"]))
                else:
                    flag_row[f"flag_{c}"] = int(r["p_reject"] >= thr[run]) if run in thr else None
                flag_row[f"seconds_{c}"] = r.get("seconds")
            rows["b11"].append(flag_row)

    # ---- blocks 12-14 from signoff.py / patient_summary.py
    for p in sorted((final / "cases").glob("*.json")):
        case = read_json(p)
        if case.get("rq2_split") not in SPLITS:
            continue
        lines = case["ap_lines"]
        rows["b12"].append(dict(case_id=case["case_id"], split=case["rq2_split"],
                                n_ap_lines=len(lines), n_assessment=sum(l["section"] == "Assessment" for l in lines),
                                n_plan=sum(l["section"] == "Plan" for l in lines),
                                n_flagged=sum(l["status"] == "flagged" for l in lines),
                                n_not_checked=sum(l["status"] == "not_checked" for l in lines),
                                n_signed=len(case["signed_note"]["assessment"]) + len(case["signed_note"]["plan"]),
                                n_open_questions=len(case["open_questions"])))
        sp = final / "summaries" / f"{case['case_id']}.json"
        summ = read_json(sp) if sp.exists() else None
        if summ:
            for variant, sents in (("verified_draft", summ["draft"]), ("unverified", summ["unverified_summary"])):
                for i, s in enumerate(sents):
                    rows["b13"].append(dict(case_id=case["case_id"], split=case["rq2_split"], variant=variant,
                                            sentence_index=i, part=s.get("part", ""), text=s["text"]))
            fin = {s["text"] for s in summ["verified_summary"]}
            for i, s in enumerate(summ["draft"]):
                rows["b14"].append(dict(case_id=case["case_id"], split=case["rq2_split"], variant="verified",
                                        sentence_index=i, text=s["text"], p_vs_signed=s.get("p_vs_signed"),
                                        p_vs_dialogue=next((x.get("p_vs_dialogue") for x in summ["verified_summary"]
                                                            if x["text"] == s["text"]), None),
                                        kept=int(s["text"] in fin)))
            for i, s in enumerate(summ["unverified_summary"]):
                rows["b14"].append(dict(case_id=case["case_id"], split=case["rq2_split"], variant="unverified",
                                        sentence_index=i, text=s["text"], p_vs_signed=s.get("p_vs_signed"),
                                        p_vs_dialogue=s.get("p_vs_dialogue"), kept=""))
        combined[case["case_id"]] = dict(case, patient_summary=summ,
                                         facts=[r for r in rows["b06"] if r["case_id"] == case["case_id"]],
                                         scores=[r for r in rows["b11"] if r["case_id"] == case["case_id"]])

    names = dict(b04="b04_statements", b05="b05_components", b06="b06_facts", b07="b07_fact_checks",
                 b08="b08_links", b09="b09_references", b10="b10_chain_scores", b11="b11_flags",
                 b12="b12_signoff", b13="b13_summary_drafts", b14="b14_summary_checks")
    counts = {names[k]: write_csv(blocks / f"{names[k]}.csv", v) for k, v in rows.items()}

    # ---------------------------------------------------------------- metrics.json
    def by_split(rs):
        g = defaultdict(list)
        for r in rs:
            g[r["split"]].append(r)
        return g

    m = {"files": counts, "runs": runs_used, "thresholds": thr}
    real = [r for r in rows["b04"] if r["origin"] == "real"]
    m["b04_statement_splitter"] = {sp: dict(
        cases=len({r["case_id"] for r in rs}),
        statements_kept=sum(not r["excluded"] for r in rs if r["origin"] == "real"),
        filler_lines_excluded=sum(r["excluded"] for r in rs if r["origin"] == "real"),
        assessment=sum(r["section"] == "Assessment" and not r["excluded"] for r in rs if r["origin"] == "real"),
        plan=sum(r["section"] == "Plan" and not r["excluded"] for r in rs if r["origin"] == "real"),
        statements_per_case=share(sum(not r["excluded"] for r in rs if r["origin"] == "real"),
                                  len({r["case_id"] for r in rs})),
        planted=dict(Counter(r["error_type"] for r in rs if r["origin"] == "planted")))
        for sp, rs in by_split(rows["b04"]).items()}
    m["b05_claim_splitter"] = {sp: dict(
        pieces=len(rs), statements=len({r["statement_id"] for r in rs}),
        share_split=share(len({r["statement_id"] for r in rs if r["n_components"] > 1}), len({r["statement_id"] for r in rs})),
        pieces_per_statement=share(len(rs), len({r["statement_id"] for r in rs})))
        for sp, rs in by_split(rows["b05"]).items()}
    m["b06_fact_collector"] = {sp: dict(
        facts=len(rs), facts_per_case=share(len(rs), len({r["case_id"] for r in rs})),
        by_category=dict(Counter(r["category"] for r in rs)),
        cases_without_facts=len({e for e in {r["case_id"] for r in rows["b04"] if r["split"] == sp}}
                                - {r["case_id"] for r in rs}))
        for sp, rs in by_split(rows["b06"]).items()}
    m["b07_fact_checker"] = {sp: dict(facts=len(rs), share_kept=share(sum(r["kept"] for r in rs), len(rs)),
                                      mean_p_supported=avg([r["p_supported"] for r in rs]))
                             for sp, rs in by_split(rows["b07"]).items()}
    m["b08_fact_linker"] = {sp: dict(pieces=len(rs), mean_facts_linked=avg([r["n_linked"] for r in rs]),
                                     share_pieces_without_facts=share(sum(r["n_linked"] == 0 for r in rs), len(rs)))
                            for sp, rs in by_split(rows["b08"]).items()}
    m["b09_reference_lookup"] = {sp: dict(pieces=len(rs),
                                          reference_coverage=share(sum(r["reference_found"] for r in rs), len(rs)),
                                          mean_passages=avg([r["n_passages"] for r in rs]))
                                 for sp, rs in by_split(rows["b09"]).items()}
    m["b10_chain_judge"] = {sp: {f"mean_p_broken_{c}_{g}": avg([r[f"p_broken_{c}"] for r in rs if r["gold_label"] == lab])
                                 for c in ("U3", "U4") for g, lab in (("real", "valid"), ("planted", "unsupported"))}
                            for sp, rs in by_split(rows["b10"]).items()}
    m["b11_flagger_rq2"] = {}
    for sp in SPLITS:
        rep = C.REPORT_DIR / sp
        if not rep.exists():
            continue
        m["b11_flagger_rq2"][sp] = dict(
            table=read_metrics_csv(rep / "metrics.csv"),
            recall_by_error_type=read_metrics_csv(rep / "recall_by_error_type.csv"),
            paired_comparisons_and_H2=read_json(rep / "summary.json") if (rep / "summary.json").exists() else None,
            note="test numbers are the results; dev numbers only chose the thresholds")
    m["b12_signoff"] = read_json(final / "signoff_summary.json") if (final / "signoff_summary.json").exists() else None
    m["b13_b14_patient_summary_H3"] = read_json(final / "patient_summary_metrics.json") \
        if (final / "patient_summary_metrics.json").exists() else None
    m["verifier_training"] = read_json(a.train_info) if a.train_info and Path(a.train_info).exists() else None

    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(json.dumps(m, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "combined.json").write_text(json.dumps(combined, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(counts, indent=1))
    print(f"wrote {out}/ (blocks/*.csv, metrics.json, combined.json: {len(combined)} cases)")


if __name__ == "__main__":
    main()
