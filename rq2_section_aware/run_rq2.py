"""Run one RQ2 condition on the frozen statement set. Resumable; one JSONL row per statement.

  python run_rq2.py --condition U1 --split test1
  python run_rq2.py --condition U2 --split test1                    # whole (pre-A/P) dialogue
  python run_rq2.py --condition U2 --split test1 --evidence topk --k 5   # S2: top-k retrieved turns
  python run_rq2.py --condition U3 --split test1
  python run_rq2.py --condition U4 --split test1 --k 3
  add --setting full to use the original dialogue (doctor's spoken A/P included); default pre-A/P.

Every row stores p_reject (a score where higher = more likely to reject) so evaluate_rq2.py can apply
dev-tuned thresholds and draw retention/recall trade-off curves. Rejection = flag OR delete for every
condition, so no condition can win by never deleting.
"""
import argparse
import importlib.util
import os
import sys

import config as C
from common import JsonlCache, Timer, load_encounters, load_statements, turns_to_text
from prompts import chain_messages, entail_messages


# ======================================================================= U1: DeBERTa + uMedSum RTB-TS
class _GenDecomposer:
    """uMedSum atomic decomposition prompt sent to the generator LLM (if Ollama/llama3 is unavailable)."""

    def __init__(self):
        from llm import GenLLM
        base = _load_baseline_decomposer_module()
        self.prompt, self.parse, self.fallback = base.DECOMPOSITION_PROMPT, base.AtomicDecomposer._parse_facts, \
            base.AtomicDecomposer.fallback_clause_split
        self.real = base.AtomicDecomposer._is_real_split
        self.llm = GenLLM()

    def decompose_with_info(self, sentence):
        if len(sentence.split()) <= 4:
            return [sentence], "too_short"
        facts = self.parse(self.llm.chat("You are a helpful assistant.", self.prompt.format(statement=sentence),
                                         max_tokens=400))
        if self.real(sentence, facts):
            return facts, "llm"
        rb = self.fallback(sentence)
        return (rb, "rule_based") if self.real(sentence, rb) else ([sentence], "unsplit")


def _load_baseline_decomposer_module():
    path = C.REPO / "Baseline_Implementation" / "umedsum_pipeline_baseline" / "stage_2" / "atomic_decomposer.py"
    spec = importlib.util.spec_from_file_location("umedsum_atomic_decomposer", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_u1_decomposer():
    if os.environ.get("U1_DECOMPOSER", "ollama") == "gen":
        return _GenDecomposer()
    mod = _load_baseline_decomposer_module()  # exactly the baseline's LLaMA-3-8B (Ollama) decomposer
    return mod.AtomicDecomposer(ollama_url=C.OLLAMA_BASE, model=C.OLLAMA_MODEL)


def u1_statement(premise, claim, nli, decomposer):
    te, tc, ta, max_depth = C.UMEDSUM_TE, C.UMEDSUM_TC, C.UMEDSUM_TA, C.UMEDSUM_MAX_DEPTH
    sc = nli.score(premise, claim)
    e, n, c = sc["entailment"], sc["neutral"], sc["contradiction"]
    det = dict(entailment=e, neutral=n, contradiction=c)
    if e > te:
        return dict(decision="keep", path="faithful", **det, atoms=[])
    if n + c > tc:
        return dict(decision="reject", path="confabulated", **det, atoms=[])

    atoms_log = []

    def rec(unit, depth, parent_e):
        atoms, method = decomposer.decompose_with_info(unit)
        unchanged = len(atoms) == 1 and atoms[0].strip().lower() == unit.strip().lower()
        if depth > 0 and unchanged:
            atoms_log.append(dict(atom=unit, entailment=parent_e, kept=False, depth=depth))
            return
        for a in atoms:
            s = nli.score(premise, a)
            if s["entailment"] > ta:
                atoms_log.append(dict(atom=a, entailment=s["entailment"], kept=True, depth=depth + 1))
            elif s["neutral"] + s["contradiction"] <= tc and depth + 1 < max_depth and len(a.split()) > 4:
                rec(a, depth + 1, s["entailment"])
            else:
                atoms_log.append(dict(atom=a, entailment=s["entailment"], kept=False, depth=depth + 1))

    rec(claim, 0, e)
    kept = sum(a["kept"] for a in atoms_log)
    # any discarded atom = part of the statement was deleted -> statement counts as rejected
    decision = "keep" if atoms_log and kept == len(atoms_log) else "reject"
    return dict(decision=decision, path="decomposed", kept_fraction=kept / max(1, len(atoms_log)), **det,
                atoms=atoms_log)


# ======================================================================= evidence helpers
def evidence_turns(enc, setting):
    if setting == "preap":
        if "turns_preap" not in enc:
            sys.exit(f"{enc['encounter_id']} has no turns_preap - run mask_ap.py first (or use --setting full)")
        return enc["turns_preap"]
    return enc["turns"]


def verifier_chunks(verifier, turns, budget):
    """Split a long dialogue into turn-aligned chunks that fit the verifier context."""
    chunks, cur, size = [], [], 0
    for t in turns:
        n = verifier.n_tokens(f"[{t['tid']}] {t['speaker']}: {t['text']}") + 2
        if cur and size + n > budget:
            chunks.append(cur)
            cur, size = cur[-1:], verifier.n_tokens(cur[-1]["text"])
        cur.append(t)
        size += n
    chunks.append(cur)
    return chunks


# ======================================================================= main loop
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--condition", required=True, choices=["U1", "U2", "U3", "U4"])
    ap.add_argument("--split", default="test1")
    ap.add_argument("--setting", default="preap", choices=["preap", "full"])
    ap.add_argument("--evidence", default="whole", choices=["whole", "topk"], help="U2 only (S2)")
    ap.add_argument("--k", type=int, default=None, help="top-k turns (U2 topk) or reference passages (U4)")
    ap.add_argument("--limit", type=int, help="first N encounters only (smoke tests)")
    ap.add_argument("--tag", default="", help="extra run-name suffix, e.g. verifier name for S1")
    a = ap.parse_args()

    encs = load_encounters(a.split)
    stmts = load_statements(a.split)
    if a.limit:  # first N encounters (keeps their valid AND planted statements together)
        keep = set(list(encs)[: a.limit])
        stmts = [s for s in stmts if s["encounter_id"] in keep]
    vname = C.VERIFIER_NAME or ("" if a.condition == "U1" else C.VERIFIER_BACKEND)
    parts = [a.condition, a.setting]
    if a.condition == "U2" and a.evidence == "topk":
        parts.append(f"top{a.k or C.TURN_TOP_K}")
    if a.condition == "U4":
        parts.append(f"ref{a.k or C.REF_TOP_K}")
    if a.condition in ("U3", "U4"):
        from chain import LINKER
        parts.append(f"link-{LINKER}")
    parts += [p for p in (vname, a.tag) if p]
    run_name = "_".join(parts)
    out = JsonlCache(C.RUNS_DIR / a.split / f"{run_name}.jsonl")
    print(f"run {run_name}: {len(stmts)} statements, {sum(s['statement_id'] in out for s in stmts)} cached")

    nli = verifier = gen = decomposer = ref_index = None
    if a.condition == "U1":
        from nli_deberta import DebertaNLI
        nli, decomposer = DebertaNLI(), make_u1_decomposer()
    else:
        from verifier import make_verifier
        verifier = make_verifier()
    if a.condition in ("U3", "U4"):
        from llm import GenLLM
        gen = GenLLM()
        decomp_cache = JsonlCache(C.RUNS_DIR / a.split / "chain_components.jsonl")
        link_cache = JsonlCache(C.RUNS_DIR / a.split / f"chain_links_{a.setting}.jsonl")
    if a.condition == "U4":
        from medlineplus import load_reference_index
        ref_index = load_reference_index()

    features_by_enc, feat_index, skipped = {}, {}, set()
    for i, s in enumerate(stmts, 1):
        if s["statement_id"] in out:
            continue
        enc = encs[s["encounter_id"]]
        turns = evidence_turns(enc, a.setting)
        rec = dict(statement_id=s["statement_id"], condition=a.condition, run=run_name)
        with Timer() as tm:
            if a.condition == "U1":
                r = u1_statement(turns_to_text(turns, with_ids=False), s["claim"], nli, decomposer)
                rec.update(r, p_reject=1.0 - r["entailment"], reject=r["decision"] == "reject")

            elif a.condition == "U2":
                if a.evidence == "topk":
                    from retrieval import turn_index
                    k = a.k or C.TURN_TOP_K
                    hits = turn_index(turns).search(s["claim"], k=k)
                    sel = sorted(hits, key=lambda h: int(h["tid"][1:]))
                    chunks = [[{kk: h[kk] for kk in ("tid", "speaker")} | {"text": h["text"].split(": ", 1)[-1]}
                               for h in sel]]
                    rec["retrieved_turns"] = [h["tid"] for h in hits]
                else:
                    chunks = verifier_chunks(verifier, turns, C.VERIFIER_MAX_INPUT_TOKENS - 400)
                best_sup, best_con = 0.0, 0.0
                for ch in chunks:
                    pr = verifier.score(entail_messages(turns_to_text(ch), s["claim"]), C.LABELS_ENTAIL)["probs"]
                    best_sup, best_con = max(best_sup, pr["supported"]), max(best_con, pr["contradicted"])
                rec.update(p_supported=best_sup, p_contradicted=best_con, n_chunks=len(chunks),
                           p_reject=1.0 - best_sup, reject=best_sup < C.TAU_ENTAIL)

            else:  # U3 / U4
                import chain
                ek = (s["encounter_id"], a.setting)
                if ek not in features_by_enc:
                    e2 = dict(enc, turns=turns, setting=a.setting)
                    feats = chain.extract_features(e2, gen)
                    features_by_enc[ek] = chain.ground_features(e2, feats, verifier=verifier)
                    if chain.LINKER == "retrieval":
                        from retrieval import HybridIndex
                        feat_index[ek] = HybridIndex([f for f in features_by_enc[ek] if f.get("grounded", True)])
                feats = features_by_enc[ek]
                if not feats:  # extraction failed (chain.py warned): write nothing, so a rerun retries it
                    skipped.add(s["encounter_id"])
                    continue
                fmap = {f["fid"]: f for f in feats}
                comps = chain.decompose(s, gen, decomp_cache)
                comp_logs, p_broken_max = [], 0.0
                for ci, comp in enumerate(comps):
                    ids = chain.link(s["statement_id"], ci, s["section"], comp, feats, gen, link_cache,
                                     feat_index.get(ek))
                    linked = [fmap[x] for x in ids]
                    passages, covered = [], None
                    if a.condition == "U4":
                        q = comp + " " + " ".join(f["text"] for f in linked)
                        hits = ref_index.search(q, k=a.k or C.REF_TOP_K)
                        passages = [h for h in hits if h["cos"] >= C.REF_MIN_COS]
                        covered = bool(passages)
                    pr = verifier.score(chain_messages(s["section"], comp, linked, passages), C.LABELS_CHAIN)["probs"]
                    p_broken_max = max(p_broken_max, pr["chain_broken"])
                    comp_logs.append(dict(component=comp, feature_ids=ids, p_broken=pr["chain_broken"],
                                          passages=[dict(pid=p["pid"], title=p["title"], section=p["section"],
                                                         cos=round(p["cos"], 3)) for p in passages],
                                          reference_found=covered))
                rec.update(components=comp_logs, p_reject=p_broken_max, reject=p_broken_max >= C.TAU_CHAIN,
                           n_features=len(feats), n_grounded=sum(f.get("grounded", True) for f in feats))
        rec["seconds"] = round(tm.seconds, 3)
        out.put(rec)
        if i % 25 == 0:
            print(f"  {i}/{len(stmts)}")
    if skipped:
        print(f"INCOMPLETE: no features for {sorted(skipped)}; their statements were not scored. "
              f"Rerun the same command.")
    print("done:", out.path)


if __name__ == "__main__":
    main()
