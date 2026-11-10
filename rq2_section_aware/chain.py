"""Evidence-chain components shared by U3 and U4 (all intermediate outputs cached and logged, so U3 and
U4 see IDENTICAL features, links and components; they differ only in the reference passages).

  1. extract_features(encounter)   dialogue -> patient-specific clinical features, each citing turns
  2. ground_features(...)          each feature checked against its cited turns (drop ungrounded ones)
  3. decompose(statement)          A/P statement -> reasoning components (one conclusion / action each)
  4. link(component, features)     -> ids of the features the component rests on (or conflicts with)
  5. judge (in conditions.py)      verifier: do the linked features (+ references) justify it?

Steps 1, 3, 4 use the generator LLM (not the verifier). LINKER=retrieval swaps step 4 for hybrid
retrieval over features, so a reviewer can check the gain does not come from the larger generator.
"""
import os
import re
from typing import Dict, List

import config as C
from common import JsonlCache, read_json, turns_to_text, write_json
from prompts import entail_messages

LINKER = os.environ.get("LINKER", "llm")            # "llm" | "retrieval"
CHAIN_DECOMPOSE = os.environ.get("CHAIN_DECOMPOSE", "1") == "1"

FEAT_SYSTEM = ("You extract patient-specific clinical features from a doctor-patient encounter. "
               "Output JSON only.")
FEAT_USER = """Encounter (turn ids in brackets):
{dialogue}

List every clinically relevant patient-specific feature stated in the encounter: symptoms (with onset,
duration, severity, location, laterality), pertinent negatives, past history, medications and doses,
allergies, social and family history, vital signs, examination findings, test and imaging results, and the
patient's stated preferences or decisions. Do NOT include the doctor's diagnoses, impressions or plans.
One fact per feature, written as a short third-person statement, citing the turn ids it comes from.

Return JSON: {{"features": [{{"text": "...", "category": "symptom|negative|history|medication|allergy|social|family|vital|exam|result|preference", "turns": ["T3", "T4"]}}]}}"""

DECOMP_SYSTEM = "You split clinical Assessment/Plan statements into components. Output JSON only."
DECOMP_USER = """Split the statement into its separate clinical conclusions or actions (one diagnosis,
one judgement, one test, one medication, one referral or one instruction each). Keep wording and any
'Regarding <problem>:' prefix context; do not add information. If it is already a single component, return it unchanged.

Section: {section}
Statement: {claim}

Return JSON: {{"components": ["...", "..."]}}"""

LINK_SYSTEM = "You link clinical note statements to the patient features they rely on. Output JSON only."
LINK_USER = """Patient features:
{features}

{section} statement: {claim}

Select the features a clinician would use to decide whether this statement is justified for this patient:
the features it is based on, AND any feature that argues against it. Do not judge whether the statement is
correct. Select at most {k}. If none are relevant, return an empty list.

Return JSON: {{"feature_ids": ["F1", "F4"]}}"""


# ---------------------------------------------------------------- 1-2 features
def feature_path(enc):
    """Features depend on the evidence setting (full vs pre-A/P dialogue)."""
    return C.RUNS_DIR / "features" / enc.get("setting", "full") / f"{enc['encounter_id']}.json"


def extract_features(enc: Dict, llm) -> List[Dict]:
    p = feature_path(enc)
    if p.exists():
        return read_json(p)["features"]
    valid_tids = {t["tid"] for t in enc["turns"]}
    out = llm.chat_json(FEAT_SYSTEM, FEAT_USER.format(dialogue=turns_to_text(enc["turns"])),
                        max_tokens=2048) or {}
    feats = []
    for f in out.get("features", []) if isinstance(out, dict) else []:
        text = (f.get("text") or "").strip()
        if not text:
            continue
        turns = [t for t in (f.get("turns") or []) if t in valid_tids]
        feats.append(dict(fid=f"F{len(feats) + 1}", text=text, category=f.get("category", ""), turns=turns))
    if not feats:
        # do NOT cache an empty list: every statement of this encounter would become chain_broken
        print(f"  WARNING {enc['encounter_id']}: feature extraction returned nothing; will retry next run")
        return feats
    write_json(p, {"encounter_id": enc["encounter_id"], "features": feats, "grounded": False})
    return feats


def ground_features(enc: Dict, feats: List[Dict], verifier=None, nli=None) -> List[Dict]:
    """Per-step check 1: is each feature supported by the turns it cites? Results stored on the feature."""
    p = feature_path(enc)
    if not p.exists():
        return feats
    blob = read_json(p)
    if blob.get("grounded"):
        return blob["features"]
    by_tid = {t["tid"]: t for t in enc["turns"]}
    for f in feats:
        if C.FEATURE_GROUNDING == "off" or (verifier is None and nli is None):
            f["ground_p"], f["grounded"] = 1.0, True
            continue
        ev_turns = [by_tid[t] for t in f["turns"]] if f["turns"] else enc["turns"]
        # include one neighbouring turn on each side: patient answers often need the doctor's question
        ids = sorted({i for t in ev_turns for i in (int(t["tid"][1:]) - 1, int(t["tid"][1:]), int(t["tid"][1:]) + 1)
                      if f"T{i}" in by_tid}) if f["turns"] else None
        evidence = turns_to_text([by_tid[f"T{i}"] for i in ids]) if ids else turns_to_text(enc["turns"])
        if C.FEATURE_GROUNDING == "nli" and nli is not None:
            p_sup = nli.score(evidence, f["text"])["entailment"]
        else:
            p_sup = verifier.score(entail_messages(evidence, f["text"]), C.LABELS_ENTAIL)["probs"]["supported"]
        f["ground_p"], f["grounded"] = round(float(p_sup), 4), p_sup >= 0.5
    write_json(p, {"encounter_id": enc["encounter_id"], "features": feats, "grounded": True})
    return feats


# ---------------------------------------------------------------- 3 decomposition
def decompose(stmt: Dict, llm, cache: JsonlCache) -> List[str]:
    if stmt["statement_id"] in cache:
        return cache.get(stmt["statement_id"])["components"]
    comps = [stmt["claim"]]
    if CHAIN_DECOMPOSE and len(stmt["text"].split()) > 8:
        out = llm.chat_json(DECOMP_SYSTEM, DECOMP_USER.format(section=stmt["section"], claim=stmt["claim"]),
                            max_tokens=500) or {}
        got = [c.strip() for c in (out.get("components") or []) if isinstance(c, str) and c.strip()] \
            if isinstance(out, dict) else []
        if got:
            prefix = re.match(r"^(Regarding [^:]+:)\s*", stmt["claim"])
            comps = [c if (not prefix or c.startswith("Regarding")) else f"{prefix.group(1)} {c}" for c in got]
    cache.put({"statement_id": stmt["statement_id"], "components": comps})
    return comps


# ---------------------------------------------------------------- 4 linking
def link(stmt_id: str, comp_idx: int, section: str, component: str, feats: List[Dict], llm,
         cache: JsonlCache, feat_index=None) -> List[str]:
    key = f"{stmt_id}#{comp_idx}#{LINKER}"
    if key in cache:
        return cache.get(key)["feature_ids"]
    usable = [f for f in feats if f.get("grounded", True)]
    if not usable:
        ids = []
    elif LINKER == "retrieval":
        ids = [h["fid"] for h in feat_index.search(component, k=C.MAX_LINKED_FEATURES)]
    else:
        flist = "\n".join(f"[{f['fid']}] {f['text']}" for f in usable)
        out = llm.chat_json(LINK_SYSTEM, LINK_USER.format(features=flist, section=section, claim=component,
                                                         k=C.MAX_LINKED_FEATURES), max_tokens=300) or {}
        valid = {f["fid"] for f in usable}
        ids = [i for i in (out.get("feature_ids") or [] if isinstance(out, dict) else []) if i in valid]
        ids = list(dict.fromkeys(ids))[:C.MAX_LINKED_FEATURES]
    cache.put({"statement_id": key, "feature_ids": ids})
    return ids
