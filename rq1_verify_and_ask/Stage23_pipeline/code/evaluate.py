"""Evaluation of systems A (Stage 1), B (+verification) and C (+omission/ask) on S/O only.

Kept separate from inference: it reads output/stage23_output.json. The reference S/O is used only
here (reference metrics and fact extraction), never by a generation/verification/detection module.

Metric groups
  A  reference-based:  ROUGE-1/2/L/Lsum, BERTScore (S/O vs reference S/O)
  B  grounding:        claim-level NLI rates vs the conversation (+ optional SummaC)
  C  task-specific:    atomic/critical fact recall, valid-claim retention, gap-detection P/R,
                       fact recovery, unsupported/duplicate additions, question redundancy, gap resolution

NLI-based rates are automatic proxies. Use annotation_claims.csv for a human-labelled subset and check
agreement. Pass --eval-nli-model to score with a different NLI model than the one used by the verifier
(otherwise B's grounding is partly circular).

  python evaluate.py --split test
  python evaluate.py --split dev --skip-grounding      # fast: reference metrics + facts only
"""
import argparse
import csv
import random
from collections import defaultdict
from statistics import mean

import config as C
from common import read_json, so_to_text, write_json

SYSTEMS = {"A_stage1": "stage1_so", "B_verified": "stage2_so", "C_final": "stage3_so"}

FACT_SYSTEM = "You extract clinical facts from a reference note for evaluation."
FACT_PROMPT = (
    "Reference Subjective/Objective note:\n{note}\n\n"
    "List every atomic clinical fact stated in the note (one proposition each, standalone third-person, "
    "negations kept). Skip 'Not specified' / absence-of-documentation statements. Mark a fact critical=true "
    "if it is a diagnosis, medication/dose, allergy, key presenting symptom, abnormal finding or an "
    "important denial; otherwise false.\n"
    'Return JSON: {{"facts": [{{"fact": "...", "critical": true}}]}}'
)


def avg(xs):
    xs = [x for x in xs if x is not None]
    return round(mean(xs), 4) if xs else None


def rate(num, den):
    return round(num / den, 4) if den else None


# ------------------------------------------------------------------ A: reference-based
def reference_metrics(records):
    out = {s: {} for s in SYSTEMS}
    from rouge_score import rouge_scorer
    scorer = rouge_scorer.RougeScorer(["rouge1", "rouge2", "rougeL", "rougeLsum"], use_stemmer=True)
    # "so_" = Subjective+Objective together; "subj_" = Subjective only. The reference Objective is largely
    # not grounded in the conversations, so the Subjective-only scores are the more trustworthy ones.
    views = {"so_": (lambda x: so_to_text(x), "S/O"),
             "subj_": (lambda x: (x.get("subjective") or "").strip(), "Subjective")}
    for prefix, (to_text, _) in views.items():
        refs = [to_text(r["reference_so"]) for r in records]
        for sname, key in SYSTEMS.items():
            preds = [to_text(r[key]) for r in records]
            scores = [scorer.score(ref, pred) for ref, pred in zip(refs, preds)]
            for m in ("rouge1", "rouge2", "rougeL", "rougeLsum"):
                out[sname][f"{prefix}{m}_f"] = avg([s[m].fmeasure for s in scores])
            try:
                from bert_score import score as bscore
                _, _, f1 = bscore([p or " " for p in preds], [x or " " for x in refs], lang="en", verbose=False)
                out[sname][f"{prefix}bertscore_f1"] = round(f1.mean().item(), 4)
            except Exception as exc:
                out[sname][f"{prefix}bertscore_f1"] = f"not computed: {type(exc).__name__}"
    return out


def summac_scores(records):
    try:
        from summac.model_summac import SummaCConv
        model = SummaCConv(models=["vitc"], bins="percentile", granularity="sentence",
                           nli_labels="e", device="cuda", start_file="default", agg="mean")
    except Exception as exc:
        return {s: f"not computed: {type(exc).__name__}" for s in SYSTEMS}
    out = {}
    for sname, key in SYSTEMS.items():
        sc = model.score([r["conversation"] for r in records], [so_to_text(r[key]) for r in records])["scores"]
        out[sname] = round(float(mean(sc)), 4)
    return out


# ------------------------------------------------------------------ B: grounding
def grounding(records, verifier, nli, cache, cache_path):
    """Claim-level NLI against the conversation, sentence-first like Stage 2.

    A sentence that is entailed as a whole is one supported unit (no splitting, so splitting artifacts
    such as lost negations cannot create false contradictions). Only sentences that are not fully
    supported are split into atomic claims, and those atoms are scored. Systems A and B use the
    same procedure, so the comparison is fair. Results are saved after every case.
    """
    from common import is_placeholder, split_sentences, strip_bullet
    per_system = {s: defaultdict(list) for s in SYSTEMS}
    claim_rows = []
    scored = {}  # (case, text) -> NLI result; systems A and B share most sentences

    def nli_score(case_id, conv, text):
        k = (case_id, text)
        if k not in scored:
            scored[k] = nli.score(conv, text)
        return scored[k]

    for n, r in enumerate(records, 1):
        for sname, key in SYSTEMS.items():
            ck = f"{r['case_id']}|{sname}|v2"
            if ck not in cache:
                rows = []
                for section in ("subjective", "objective"):
                    for raw in (r[key].get(section) or "").splitlines():
                        if not raw.strip():
                            continue
                        for sent in split_sentences(strip_bullet(raw)[1]):
                            if is_placeholder(sent):
                                continue
                            s = nli_score(r["case_id"], r["conversation"], sent)
                            if s["entailment"] >= C.TE:
                                units = [(sent, s, "sentence")]
                            else:
                                units = [(a, nli_score(r["case_id"], r["conversation"], a), "atom")
                                         for a in verifier.decomposer.decompose(sent)]
                            for text, sc, kind in units:
                                rows.append({"section": section, "claim": text, "unit": kind,
                                             "entailment": sc["entailment"], "contradiction": sc["contradiction"],
                                             "evidence": sc["support_evidence"]})
                cache[ck] = rows
                write_json(cache_path, cache)
            for row in cache[ck]:
                e, c = row["entailment"], row["contradiction"]
                label = ("supported" if e >= C.TE else "contradicted" if c >= C.TCONTRA
                         else "uncertain" if e >= C.TA else "unsupported")
                per_system[sname]["labels"].append(label)
                per_system[sname]["ent"].append(e)
                claim_rows.append({"case_id": r["case_id"], "system": sname, "section": row["section"],
                                   "claim": row["claim"], "nli_label": label,
                                   "entailment": round(e, 3), "evidence": row["evidence"], "human_label": ""})
        print(f"  grounding [{n}/{len(records)}] {r['case_id']}", flush=True)
    out = {}
    for sname, d in per_system.items():
        n = len(d["labels"])
        cnt = lambda lab: sum(1 for l in d["labels"] if l == lab)
        out[sname] = {
            "num_claims": n,
            "supported_rate": rate(cnt("supported"), n),
            "uncertain_rate": rate(cnt("uncertain"), n),
            "unsupported_claim_rate": rate(cnt("unsupported") + cnt("contradicted"), n),
            "contradiction_rate": rate(cnt("contradicted"), n),
            "mean_entailment": avg(d["ent"]),
        }
    return out, claim_rows


# ------------------------------------------------------------------ C: facts
def reference_facts(records, llm, cache, cache_path):
    for n, r in enumerate(records, 1):
        if r["case_id"] in cache:
            continue
        data = llm.chat_json(FACT_SYSTEM, FACT_PROMPT.format(note=so_to_text(r["reference_so"])), num_predict=900)
        facts = data.get("facts", []) if isinstance(data, dict) else []
        cache[r["case_id"]] = [{"fact": f["fact"], "critical": bool(f.get("critical"))}
                               for f in facts if isinstance(f, dict) and f.get("fact")]
        write_json(cache_path, cache)
        print(f"  reference facts [{n}/{len(records)}] {r['case_id']}: {len(cache[r['case_id']])} facts", flush=True)
    return cache


def pmap(fn, items, workers=4):
    """Run NLI requests concurrently (the NLI server is a GPU host; a few parallel calls are fine)."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, items))


def case_fact_scores(r, cf, texts, nli, cache, cache_path):
    """Is each reference fact represented in each system's note / supported by the conversation? Cached per case."""
    saved = cache.get(r["case_id"])
    if saved and saved.get("n") == len(cf) and set(saved["represented"]) >= set(SYSTEMS):
        return {s: saved["represented"][s] for s in SYSTEMS}, saved["recoverable"]
    jobs = [(texts[s], f["fact"]) for s in SYSTEMS for f in cf] + [(r["conversation"], f["fact"]) for f in cf]
    ents = pmap(lambda j: nli.score(j[0], j[1])["entailment"], jobs)
    represented, pos = {}, 0
    for s in SYSTEMS:
        represented[s] = [e >= C.FACT_REPRESENTED_MIN for e in ents[pos:pos + len(cf)]]
        pos += len(cf)
    recoverable = [e >= C.FACT_SUPPORTED_MIN for e in ents[pos:]]
    cache[r["case_id"]] = {"n": len(cf), "represented": represented, "recoverable": recoverable}
    write_json(cache_path, cache)
    return represented, recoverable


def fact_metrics(records, facts, nli, fact_cache, fact_cache_path):
    """Fact recall per system, plus omission/recovery/addition/question metrics."""
    rec_atomic = defaultdict(list)
    rec_crit = defaultdict(list)
    rec_recoverable = defaultdict(list)
    retention_num = retention_den = 0
    om = defaultdict(int)
    q = defaultdict(int)

    for n, r in enumerate(records, 1):
        cf = facts.get(r["case_id"], [])
        texts = {s: so_to_text(r[k]) for s, k in SYSTEMS.items()}
        represented, recoverable = case_fact_scores(r, cf, texts, nli, fact_cache, fact_cache_path)
        print(f"  fact scoring [{n}/{len(records)}] {r['case_id']}", flush=True)
        for s in SYSTEMS:
            if cf:
                rec_atomic[s].append(rate(sum(represented[s]), len(cf)))
                crit = [i for i, f in enumerate(cf) if f["critical"]]
                if crit:
                    rec_crit[s].append(rate(sum(represented[s][i] for i in crit), len(crit)))
                rec = [i for i in range(len(cf)) if recoverable[i]]
                if rec:
                    rec_recoverable[s].append(rate(sum(represented[s][i] for i in rec), len(rec)))

        # valid-claim retention (proxy): facts of A that are recoverable and represented in A stay in B
        for i in range(len(cf)):
            if recoverable[i] and represented["A_stage1"][i]:
                retention_den += 1
                retention_num += int(represented["B_verified"][i])

        # genuine omissions: in the reference, recoverable from the conversation, absent from verified S/O
        genuine = [i for i in range(len(cf)) if recoverable[i] and not represented["B_verified"][i]]
        flagged = [c["statement"] for c in r.get("stage3_candidate_log", []) if c.get("statement")]
        n_flagged_all = len(r.get("stage3_candidate_log", []))
        matched_fact, matched_flag = set(), set()
        pairs = [(fi, fl) for fi in genuine for fl in range(len(flagged))]
        ents = pmap(lambda p: nli.score(flagged[p[1]], cf[p[0]]["fact"])["entailment"], pairs)
        for (fi, fl), e in zip(pairs, ents):
            if e >= C.FACT_REPRESENTED_MIN:
                matched_fact.add(fi)
                matched_flag.add(fl)
        om["genuine"] += len(genuine)
        om["genuine_detected"] += len(matched_fact)
        om["flagged"] += n_flagged_all
        om["flagged_genuine"] += len(matched_flag)
        if "C_final" in SYSTEMS:
            om["genuine_recovered"] += sum(1 for i in genuine if represented["C_final"][i])

        for a in r.get("stage3_added", []):
            om["added"] += 1
            om["added_unsupported"] += int(nli.score(r["conversation"], a["statement"])["entailment"]
                                           < C.FACT_SUPPORTED_MIN)
            om["added_duplicate"] += int(nli.score(texts["B_verified"], a["statement"])["entailment"]
                                         >= C.DUP_ENTAIL_MIN)

        g = r.get("gaps", {})
        q["generated"] += g.get("num_generated", len(g.get("gaps", [])))
        q["kept"] += len(g.get("gaps", []))
        q["redundant"] += len(g.get("dropped", []))
        q["eligible_answered"] += sum(1 for x in g.get("gaps", []) if x.get("answer"))
        q["resolved"] += sum(1 for x in g.get("gaps", []) if x.get("status") == "resolved")

    recall = {s: {"atomic_fact_recall": avg(rec_atomic[s]), "critical_fact_recall": avg(rec_crit[s]),
                  "recall_of_recoverable_facts": avg(rec_recoverable[s])} for s in SYSTEMS}
    task = {
        "valid_claim_retention_proxy": rate(retention_num, retention_den),
        "gap_detection_recall": rate(om["genuine_detected"], om["genuine"]),
        "gap_detection_precision": rate(om["flagged_genuine"], om["flagged"]),
        "fact_recovery_rate": rate(om["genuine_recovered"], om["genuine"]),
        "unsupported_addition_rate": rate(om["added_unsupported"], om["added"]),
        "duplicate_addition_rate": rate(om["added_duplicate"], om["added"]),
        "num_genuine_omissions": om["genuine"],
        "num_added": om["added"],
        "question_redundancy_rate": rate(q["redundant"], q["generated"]),
        "questions_kept": q["kept"],
        "gap_resolution_rate": rate(q["resolved"], q["eligible_answered"]) if q["eligible_answered"]
        else "n/a (no follow-up answers recorded)",
    }
    if "C_final" not in SYSTEMS:  # Stage-2-only run: Stage 3 / Ask metrics do not apply
        task = {k: task[k] for k in ("valid_claim_retention_proxy", "num_genuine_omissions")}
    return recall, task


# ------------------------------------------------------------------ outputs
def write_annotation_files(claim_rows, records):
    C.EVAL_DIR.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(C.RANDOM_SEED)
    sample = rnd.sample(claim_rows, min(C.ANNOTATION_SAMPLE_SIZE, len(claim_rows)))
    with open(C.EVAL_DIR / "annotation_claims.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(sample[0].keys()) if sample else ["claim"])
        w.writeheader()
        w.writerows(sample)
    qrows = [{"case_id": r["case_id"], "kind": "question", "text": g["question"], "gap": g["gap"],
              "relevant_1to5": "", "answerable_yes_no": ""} for r in records for g in r.get("gaps", {}).get("gaps", [])]
    qrows += [{"case_id": r["case_id"], "kind": "added_fact", "text": a["statement"], "gap": a["evidence"],
               "relevant_1to5": "", "answerable_yes_no": ""} for r in records for a in r.get("stage3_added", [])]
    with open(C.EVAL_DIR / "annotation_questions_and_additions.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["case_id", "kind", "text", "gap", "relevant_1to5", "answerable_yes_no"])
        w.writeheader()
        w.writerows(qrows)


def write_markdown_summary(results, path):
    """Presentation table: the same numbers as the JSON, grouped by what they answer."""
    ps = results["per_system"]
    names = list(ps)
    groups = [
        ("Similarity to the ground-truth S/O (higher is better)",
         ["subj_rouge1_f", "subj_rouge2_f", "subj_rougeLsum_f", "subj_bertscore_f1",
          "so_rouge1_f", "so_rouge2_f", "so_rougeLsum_f", "so_bertscore_f1"]),
        ("Fact coverage vs the ground-truth S/O (higher is better)",
         ["atomic_fact_recall", "critical_fact_recall", "recall_of_recoverable_facts"]),
        ("Grounding in the conversation",
         ["supported_rate", "unsupported_claim_rate", "contradiction_rate", "mean_entailment", "num_claims"]),
    ]
    lines = [f"# RQ1 results - {results['split']} split ({results['num_cases']} cases)", "",
             "A/P is not part of any score; S/O only.", ""]
    for title, keys in groups:
        lines += [f"## {title}", "", "| metric | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
        for k in keys:
            lines.append(f"| {k} | " + " | ".join(str(ps[s].get(k, "")) for s in names) + " |")
        lines.append("")
    lines += ["## Stage 3 / Ask / integrity metrics", "", "| metric | value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in results["task_metrics"].items()]
    lines += ["", "Notes: " + " ".join(results.get("notes", []))]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def print_table(results):
    keys = sorted({k for s in SYSTEMS for k in results["per_system"][s]})
    print(f"\n{'metric':34s}" + "".join(f"{s:>14s}" for s in SYSTEMS))
    for k in keys:
        print(f"{k:34s}" + "".join(f"{str(results['per_system'][s].get(k, '')):>14s}" for s in SYSTEMS))
    print("\nStage 3 / Ask task metrics (C vs B):")
    for k, v in results["task_metrics"].items():
        print(f"  {k:34s}{v}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage23-json", default=None)
    ap.add_argument("--stage2-only", action="store_true",
                    help="evaluate systems A and B from output/stage2_only/ (no Stage 3 results)")
    ap.add_argument("--split", choices=["dev", "test", "all"], default="test")
    ap.add_argument("--eval-nli-model", default=C.NLI_MODEL)
    ap.add_argument("--skip-grounding", action="store_true")
    ap.add_argument("--skip-facts", action="store_true")
    ap.add_argument("--summac", action="store_true")
    args = ap.parse_args()

    global SYSTEMS
    if args.stage2_only:
        base = C.OUTPUT_DIR / "stage2_only"
        C.EVAL_DIR = base / "evaluation"
        in_path = args.stage23_json or str(base / "stage2_output.json")
    else:
        in_path = args.stage23_json or str(C.STAGE23_JSON)
    records = [r for r in read_json(in_path)["records"]
               if r["status"] == "success" and (args.split == "all" or r.get("split") == args.split)]
    if not records:
        raise SystemExit("No successful records for this split.")
    if "stage3_so" not in records[0]:
        SYSTEMS = {k: v for k, v in SYSTEMS.items() if k != "C_final"}
        print("No Stage 3 output found: evaluating systems", list(SYSTEMS))
    C.EVAL_DIR.mkdir(parents=True, exist_ok=True)

    per_system = {s: {} for s in SYSTEMS}
    print(f"Phase 1/3: ROUGE / BERTScore on {len(records)} cases (loads roberta-large on CPU; a few minutes)", flush=True)
    for s, m in reference_metrics(records).items():
        per_system[s].update(m)
    if args.summac:
        for s, v in summac_scores(records).items():
            per_system[s]["summac_conv"] = v

    nli = claim_rows = task = None
    need_nli = not (args.skip_grounding and args.skip_facts)
    if need_nli:
        from llm_client import LLMClient
        from nli_remote import make_nli_scorer
        from atomic_decomposer import AtomicDecomposer
        from verification import ClaimVerifier
        llm = LLMClient()
        nli = make_nli_scorer(args.eval_nli_model)
        verifier = ClaimVerifier(nli, AtomicDecomposer(llm), llm, C.TE, C.TA, C.TCONTRA)
        _memo = {}  # systems A and B share most sentences; decompose each distinct sentence once
        _decompose = verifier.decomposer.decompose
        verifier.decomposer.decompose = lambda s: _memo[s] if s in _memo else _memo.setdefault(s, _decompose(s))

    claim_rows = []
    if not args.skip_grounding:
        gpath = C.EVAL_DIR / f"grounding_cache_{args.eval_nli_model.split('/')[-1]}.json"
        gcache = read_json(gpath) if gpath.exists() else {}
        print("Phase 2/3: grounding (claims vs conversation)", flush=True)
        g, claim_rows = grounding(records, verifier, nli, gcache, gpath)
        for s in SYSTEMS:
            per_system[s].update(g[s])
    stage2_retention = avg([r["stage2_stats"].get("claim_retention_rate") for r in records])

    task = {}
    if not args.skip_facts:
        fpath = C.EVAL_DIR / "reference_facts.json"
        fcache = read_json(fpath) if fpath.exists() else {}
        print("Phase 3/3: reference facts and fact recall", flush=True)
        facts = reference_facts(records, llm, fcache, fpath)
        spath = C.EVAL_DIR / f"fact_scores_cache_{args.eval_nli_model.split('/')[-1]}.json"
        scache = read_json(spath) if spath.exists() else {}
        recall, task = fact_metrics(records, facts, nli, scache, spath)
        for s in SYSTEMS:
            per_system[s].update(recall[s])
    task["claim_retention_rate_stage2"] = stage2_retention
    flags = [r["ap_unchanged"] for r in records if "ap_unchanged" in r]
    task["ap_unchanged_rate"] = rate(sum(flags), len(flags)) if flags else "not recorded (re-run to record)"

    results = {"split": args.split, "num_cases": len(records), "eval_nli_model": args.eval_nli_model,
               "thresholds": {"TE": C.TE, "TA": C.TA, "TCONTRA": C.TCONTRA, "COV_MIN": C.COV_MIN},
               "per_system": per_system, "task_metrics": task,
               "notes": ["NLI-based rates are automatic proxies; validate on annotation_claims.csv.",
                         "Reference S/O used only for reference metrics and fact extraction.",
                         "gap_resolution_rate needs recorded follow-up answers."]}
    write_json(C.EVAL_DIR / f"results_{args.split}.json", results)
    if claim_rows:
        write_annotation_files(claim_rows, records)
    write_markdown_summary(results, C.EVAL_DIR / f"results_{args.split}.md")
    print_table(results)
    print(f"\nSaved {C.EVAL_DIR / f'results_{args.split}.json'} and results_{args.split}.md")


if __name__ == "__main__":
    main()
