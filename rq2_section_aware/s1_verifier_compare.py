"""S1: verifier comparison on the same claim-evidence examples.

Input JSONL (held-out from verifier training), one example per line:
  {"id": "...", "premise": "<evidence text>", "claim": "...", "label": "supported|contradicted|unsupported",
   "error_type": "fabricated_symptom|negation_flip|medication_dose|laterality_duration|unsupported_diagnosis|plan_without_evidence|none"}

  python s1_verifier_compare.py --data data_out/s1_eval.jsonl --verifier deberta
  VERIFIER_BACKEND=hf VERIFIER_ADAPTER=/path/qlora python s1_verifier_compare.py --data ... --verifier hf --name qlora3b
  VERIFIER_BACKEND=openai VERIFIER_MODEL=qwen/qwen-2.5-7b-instruct python s1_verifier_compare.py --data ... --verifier openai --name prompted7b

Metric: macro-F1 over the three labels, per error type (that type's perturbed examples + all clean
examples), plus overall macro-F1 and seconds per claim.
DeBERTa mapping: argmax over entailment / contradiction / neutral (neutral -> unsupported).
"""
import argparse
import time

import config as C
from common import JsonlCache, read_jsonl, write_json
from prompts import entail_messages

LABELS = list(C.LABELS_ENTAIL)


def macro_f1(pairs):
    f1s = []
    for l in LABELS:
        tp = sum(p == l and g == l for g, p in pairs)
        fp = sum(p == l and g != l for g, p in pairs)
        fn = sum(p != l and g == l for g, p in pairs)
        if tp + fp + fn == 0:
            continue
        f1s.append(2 * tp / (2 * tp + fp + fn))
    return sum(f1s) / len(f1s) if f1s else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--verifier", required=True, choices=["deberta", "hf", "openai", "stub"])
    ap.add_argument("--name", default="")
    a = ap.parse_args()
    name = a.name or a.verifier
    ex = read_jsonl(a.data)
    cache = JsonlCache(C.RUNS_DIR / "s1" / f"{name}.jsonl", key="id")
    if a.verifier == "deberta":
        from nli_deberta import DebertaNLI
        nli = DebertaNLI()
    else:
        from verifier import make_verifier
        v = make_verifier(a.verifier)
    for e in ex:
        if e["id"] in cache:
            continue
        t0 = time.perf_counter()
        if a.verifier == "deberta":
            s = nli.score(e["premise"], e["claim"])
            pred = max((("supported", s["entailment"]), ("contradicted", s["contradiction"]),
                        ("unsupported", s["neutral"])), key=lambda x: x[1])[0]
        else:
            pred = v.score(entail_messages(e["premise"], e["claim"]), C.LABELS_ENTAIL)["label"]
        cache.put(dict(id=e["id"], pred=pred, seconds=time.perf_counter() - t0))
    preds = {k: r["pred"] for k, r in cache.data.items()}
    clean = [(e["label"], preds[e["id"]]) for e in ex if e.get("error_type", "none") in ("none", "")]
    res = dict(verifier=name, n=len(ex), overall_macro_f1=macro_f1([(e["label"], preds[e["id"]]) for e in ex]),
               sec_per_claim=sum(r["seconds"] for r in cache.data.values()) / max(1, len(cache.data)), per_type={})
    for et in sorted({e.get("error_type", "none") for e in ex} - {"none", ""}):
        pert = [(e["label"], preds[e["id"]]) for e in ex if e.get("error_type") == et]
        res["per_type"][et] = dict(n=len(pert), macro_f1=macro_f1(pert + clean),
                                   detect_rate=sum(p != "supported" for _, p in pert) / len(pert))
    write_json(C.REPORT_DIR / "s1" / f"{name}.json", res)
    print(res)


if __name__ == "__main__":
    main()
