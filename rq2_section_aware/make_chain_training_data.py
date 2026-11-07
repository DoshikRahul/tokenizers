"""Build A/P (chain_ok / chain_broken) training pairs for the QLoRA verifier from ACI-Bench TRAIN only.

The proposal trains one verifier with different prompts and label sets for S/O and A/P. This script
produces the A/P half, in exactly the prompt format used at test time (prompts.chain_messages).

  python build_dataset.py --splits train
  python plant_errors.py --split train && python plant_errors.py --split train --merge --accept-all
  python mask_ap.py --split train
  FEATURE_GROUNDING=off python make_chain_training_data.py
-> data_out/chain_train.jsonl  {"messages": [...], "target": "chain_ok" | "chain_broken", "source": ...}

Positives : reference A/P statements and their components (chain_ok).
Negatives : planted statements (chain_broken), plus 'swapped' statements: a diagnosis / reasoning /
            treatment statement from ANOTHER encounter whose problem does not appear in this one.
Half of the examples carry retrieved MedlinePlus passages (if the corpus exists), so the same adapter
serves U3 and U4.
"""
import random

import chain
import config as C
from common import JsonlCache, load_encounters, load_statements, norm, write_jsonl
from llm import GenLLM
from prompts import chain_messages


def main(split="train", setting="preap", swap_per_encounter=3):
    rng = random.Random(C.SEED)
    encs, stmts, gen = load_encounters(split), load_statements(split, use_audit=False), GenLLM()
    try:
        from medlineplus import load_reference_index
        ref = load_reference_index()
    except FileNotFoundError:
        ref = None
    dcache = JsonlCache(C.RUNS_DIR / split / "chain_components.jsonl")
    lcache = JsonlCache(C.RUNS_DIR / split / f"chain_links_{setting}.jsonl")
    out = []

    def add(enc_id, section, claim, feats, target, source, sid, ci):
        ids = chain.link(sid, ci, section, claim, feats, gen, lcache)
        fmap = {f["fid"]: f for f in feats}
        linked = [fmap[i] for i in ids]
        passages = []
        if ref is not None and rng.random() < 0.5:
            hits = ref.search(claim + " " + " ".join(f["text"] for f in linked), k=rng.choice([1, 3, 5]))
            passages = [h for h in hits if h["cos"] >= C.REF_MIN_COS]
        out.append(dict(messages=chain_messages(section, claim, linked, passages), target=target,
                        source=source, encounter_id=enc_id))

    by_enc = {}
    for s in stmts:
        by_enc.setdefault(s["encounter_id"], []).append(s)
    pool = [s for s in stmts if s["origin"] == "reference" and s["stmt_type"] in ("diagnosis", "reasoning", "treatment")]
    for eid, ss in by_enc.items():
        enc = dict(encs[eid], turns=encs[eid].get("turns_preap", encs[eid]["turns"]) if setting == "preap"
                   else encs[eid]["turns"], setting=setting)
        feats = chain.ground_features(enc, chain.extract_features(enc, gen))
        for s in ss:
            if s["origin"] == "planted":
                add(eid, s["section"], s["claim"], feats, "chain_broken", s["error_type"], s["statement_id"], 0)
            else:
                for ci, comp in enumerate(chain.decompose(s, gen, dcache)):
                    add(eid, s["section"], comp, feats, "chain_ok", "reference", s["statement_id"], ci)
        text_here = norm(" ".join(t["text"] for t in encs[eid]["turns"]))
        others = [o for o in pool if o["encounter_id"] != eid and o["problem"] and norm(o["problem"]) not in text_here]
        for j, o in enumerate(rng.sample(others, min(swap_per_encounter, len(others)))):
            add(eid, o["section"], o["claim"], feats, "chain_broken", "swapped", f"{eid}_SW{j}", 0)
        print(f"  {eid}: {sum(x['encounter_id'] == eid for x in out)} examples")
    rng.shuffle(out)
    write_jsonl(C.DATA_DIR / f"chain_{split}.jsonl", out)
    pos = sum(x["target"] == "chain_ok" for x in out)
    print(f"{len(out)} examples ({pos} chain_ok / {len(out) - pos} chain_broken) -> {C.DATA_DIR / f'chain_{split}.jsonl'}")


if __name__ == "__main__":
    main()
