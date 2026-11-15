"""Per-step verdict accuracy, citation precision and evidence Recall@k (proposal: 'intermediate verdicts scored').

export: sample statements from an evidence-chain run and write a sheet with one row per intermediate
        verdict for annotators:
          step=feature_grounding  is the feature supported by its cited turns?          gold: 1/0
          step=link               is this linked feature relevant to the component?     gold: 1/0
          step=chain              does the evidence chain justify the component?        gold: chain_ok/chain_broken
          step=evidence_turns     (valid statements) which turns support it?            gold: T3,T7 ...
score : read the filled sheet and report per-step accuracy, citation precision, Recall@k (S2).

  python annotate_steps.py export --split test1 --run U4_preap_ref3_link-llm_hf --n 60
  python annotate_steps.py score  --split test1 --run U4_preap_ref3_link-llm_hf [--turn-run U2_preap_top5_hf]
"""
import argparse
import random

import config as C
from common import load_encounters, load_statements, read_csv, read_json, read_jsonl, write_csv, write_json


def export(a):
    gold = {s["statement_id"]: s for s in load_statements(a.split)}
    encs = load_encounters(a.split)
    run = {r["statement_id"]: r for r in read_jsonl(C.RUNS_DIR / a.split / f"{a.run}.jsonl")}
    setting = "preap" if "_preap" in a.run else "full"
    rng = random.Random(C.SEED)
    ids = sorted(run)
    # stratify: half valid, half planted (if available)
    v = [i for i in ids if gold[i]["gold_label"] == "valid"]
    u = [i for i in ids if gold[i]["gold_label"] == "unsupported"]
    sample = rng.sample(v, min(len(v), a.n // 2)) + rng.sample(u, min(len(u), a.n - a.n // 2))
    rows, seen_enc = [], set()
    for sid in sample:
        s, r = gold[sid], run[sid]
        feats = {f["fid"]: f for f in read_json(C.RUNS_DIR / "features" / setting / f"{s['encounter_id']}.json")["features"]}
        for ci, c in enumerate(r.get("components", [])):
            rows.append(dict(step="chain", statement_id=sid, component_idx=ci, section=s["section"],
                             item=c["component"], context=" | ".join(f"[{x}] {feats[x]['text']}" for x in c["feature_ids"]),
                             system=("chain_broken" if c["p_broken"] >= C.TAU_CHAIN else "chain_ok"), gold=""))
            for fid in c["feature_ids"]:
                rows.append(dict(step="link", statement_id=sid, component_idx=ci, section=s["section"],
                                 item=f"[{fid}] {feats[fid]['text']}", context=c["component"], system="1", gold=""))
        if s["gold_label"] == "valid":
            rows.append(dict(step="evidence_turns", statement_id=sid, section=s["section"], item=s["claim"],
                             context="see encounter turns", system="", gold=""))
        if s["encounter_id"] not in seen_enc:
            seen_enc.add(s["encounter_id"])
            by_tid = {t["tid"]: t for t in encs[s["encounter_id"]].get(f"turns_{setting}" if setting == "preap" else "turns", [])}
            for f in list(feats.values())[: a.features_per_encounter]:
                rows.append(dict(step="feature_grounding", statement_id=s["encounter_id"], item=f"[{f['fid']}] {f['text']}",
                                 context=" | ".join(f"{t}: {by_tid[t]['text']}" for t in f["turns"] if t in by_tid),
                                 system=str(int(f.get("grounded", True))), gold=""))
    path = C.DATA_DIR / f"steps_{a.split}_{a.run}.csv"
    write_csv(path, rows, ["step", "statement_id", "component_idx", "section", "item", "context", "system", "gold"])
    print(f"{len(rows)} rows -> {path}")


def score(a):
    rows = [r for r in read_csv(C.DATA_DIR / f"steps_{a.split}_{a.run}.csv") if r["gold"].strip()]
    out = {}
    for step in ("feature_grounding", "link", "chain"):
        rs = [r for r in rows if r["step"] == step]
        if rs:
            out[f"{step}_accuracy"] = sum(r["system"].strip() == r["gold"].strip() for r in rs) / len(rs)
            out[f"{step}_n"] = len(rs)
    links = [r for r in rows if r["step"] == "link"]
    if links:
        out["citation_precision"] = sum(r["gold"].strip() == "1" for r in links) / len(links)
    # Recall@k: gold evidence turns vs the turns U2-topk retrieved for the same statement
    ev = {r["statement_id"]: {t.strip() for t in r["gold"].split(",") if t.strip()}
          for r in rows if r["step"] == "evidence_turns"}
    if ev and a.turn_run:
        tr = {r["statement_id"]: r for r in read_jsonl(C.RUNS_DIR / a.split / f"{a.turn_run}.jsonl")}
        recs = []
        for sid, g in ev.items():
            if sid in tr and g:
                got = set(tr[sid].get("retrieved_turns", []))
                recs.append(len(g & got) / len(g))
        if recs:
            out["evidence_recall_at_k"], out["evidence_recall_n"] = sum(recs) / len(recs), len(recs)
    write_json(C.REPORT_DIR / a.split / f"steps_{a.run}.json", out)
    print(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["export", "score"])
    ap.add_argument("--split", default="test1")
    ap.add_argument("--run", required=True)
    ap.add_argument("--turn-run", default="")
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--features-per-encounter", type=int, default=8)
    a = ap.parse_args()
    export(a) if a.cmd == "export" else score(a)
