"""Build S/O (supported / contradicted / unsupported) pairs: the entailment half of the verifier's training
data, and the S1 evaluation set. No LLM and no GPU are needed.

Source: Subjective / Objective sentences of the ACI-Bench REFERENCE notes, checked against the original
dialogue, in exactly the prompt format used at test time (prompts.entail_messages).

  supported     a reference S/O sentence, kept only if most of its content words occur in the dialogue
  contradicted  the same sentence with one rule-based edit of a value the dialogue states:
                negation_flip | laterality_duration (left<->right, a number of days/weeks/...) | medication_dose
  unsupported   fabricated_symptom: an S/O sentence from ANOTHER encounter that this dialogue does not cover

Training also gets short-evidence pairs (a few turns, as in the U3/U4 feature-grounding check and U2 top-k):
the turns around the best-matching turn (supported) and turns from elsewhere in the dialogue (unsupported).

  python make_so_training_data.py                # train -> data_out/so_train.jsonl  (train_verifier.py format)
  python make_so_training_data.py --split dev    # dev   -> data_out/s1_eval.jsonl   (s1_verifier_compare.py format)

Train on the first, evaluate S1 on the second: dev encounters are never used for verifier training.
The labels are rule-based, not human-checked; spot-check the printed samples before training.
"""
import argparse
import random
import re
from collections import Counter

import config as C
from build_dataset import AP_HEADERS
from common import read_jsonl, split_sentences, strip_bullet, turns_to_text, write_jsonl
from prompts import entail_messages

STOP = set("the a an and or of to in on at for with without by from as is are was were be been has have had he she "
           "they his her their him them it its this that these those patient patients pt reports reported denies "
           "denied states stated notes noted any some not no also who which when while there here today".split())
NUM_WORDS = "one two three four five six seven eight nine ten".split()
NEG_FLIPS = [  # (pattern, replacement); the first that matches is used
    (r"\bdenies any\b", "reports"), (r"\bdenied any\b", "reported"), (r"\bdenies\b", "reports"),
    (r"\bdenied\b", "reported"), (r"\bnegative for\b", "positive for"), (r"\bpositive for\b", "negative for"),
    (r"\bno evidence of\b", "evidence of"), (r"\bwithout\b", "with"), (r"\breports\b", "denies"),
    (r"\bendorses\b", "denies"), (r"\bcomplains of\b", "denies"),
]
DOSE = re.compile(r"\b(\d+(?:\.\d+)?)(\s?(?:mg|mcg|milligrams?|micrograms?|units?|ml|milliliters?))\b", re.I)
DURATION = re.compile(r"\b(\d+|" + "|".join(NUM_WORDS) + r")([- ](?:day|week|month|year|hour)s?)\b(?![- ]old)", re.I)
WORD_BUDGET = 1900  # whole-dialogue evidence above this is cut to the best-matching run of turns


def stems(text):
    return {w[:5] for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in STOP}


def coverage(sentence, evidence_stems):
    s = stems(sentence)
    return len(s & evidence_stems) / len(s) if s else 0.0


def so_sentences(note):
    """Sentences of every section that is not Assessment / Plan."""
    out, keep = [], False
    for raw in note.splitlines():
        line = raw.strip()
        head = line.rstrip(":").upper()
        if line and line == line.upper() and re.fullmatch(r"[A-Z][A-Z /&]{3,}", head) and len(head) <= 40:
            keep = head not in AP_HEADERS
            continue
        if keep and line:
            out += [s for s in split_sentences(strip_bullet(line)) if 4 <= len(s.split()) <= 40]
    return list(dict.fromkeys(out))


def keep_case(rep):
    """re.sub replacement that keeps a leading capital ('Right knee' -> 'Left knee')."""
    return lambda m: rep.capitalize() if m.group(0)[0].isupper() else rep


def perturb(sentence, dialogue_words, rng):
    """All rule-based contradictions of one sentence: [(error_type, new_sentence)]."""
    out = []
    for pat, rep in NEG_FLIPS:
        if re.search(pat, sentence, re.I):
            out.append(("negation_flip", re.sub(pat, keep_case(rep), sentence, count=1, flags=re.I)))
            break
    sides = re.findall(r"\b(left|right)\b", sentence, re.I)
    if sides and len({s.lower() for s in sides}) == 1 and sides[0].lower() in dialogue_words:
        other = "right" if sides[0].lower() == "left" else "left"
        if other not in dialogue_words:  # the dialogue names one side only, so the swap is a contradiction
            out.append(("laterality_duration", re.sub(r"\b(left|right)\b", keep_case(other), sentence, flags=re.I)))
    m = DURATION.search(sentence)
    if m and m.group(1).lower() in dialogue_words:
        n = int(m.group(1)) if m.group(1).isdigit() else NUM_WORDS.index(m.group(1).lower()) + 1
        free = [x for x in (n + 3, n + 5, n * 3) if str(x) not in dialogue_words]
        if free:
            out.append(("laterality_duration", sentence[:m.start(1)] + str(rng.choice(free)) + sentence[m.end(1):]))
    m = DOSE.search(sentence)
    if m and m.group(1) in dialogue_words:
        n = float(m.group(1))
        new = rng.choice([n * 2, n * 10, n / 2] if n >= 10 else [n * 2, n * 10, n + 3])
        new = str(int(new)) if new == int(new) else str(new)
        if new not in dialogue_words:
            out.append(("medication_dose", sentence[:m.start(1)] + new + sentence[m.end(1):]))
    return [(t, s) for t, s in out if s != sentence]


def full_evidence(turns, sentence):
    """Whole dialogue, or (if too long for the trainer) the run of turns that covers the sentence best."""
    sizes = [len(t["text"].split()) + 2 for t in turns]
    if sum(sizes) <= WORD_BUDGET:
        return turns
    best, best_cov = turns, -1.0
    for start in range(0, len(turns), 5):
        end, words = start, 0
        while end < len(turns) and words + sizes[end] <= WORD_BUDGET:
            words += sizes[end]
            end += 1
        cov = coverage(sentence, stems(" ".join(t["text"] for t in turns[start:end])))
        if cov > best_cov:
            best, best_cov = turns[start:end], cov
        if end == len(turns):
            break
    return best


def build(split, a):
    rng = random.Random(C.SEED)
    encs = read_jsonl(C.DATA_DIR / f"encounters_{split}.jsonl")
    pool = {e["encounter_id"]: so_sentences(e["reference_note"]) for e in encs}
    rows = []
    for e in encs:
        eid, turns = e["encounter_id"], e["turns"]
        text = " ".join(t["text"] for t in turns)
        d_stems, d_words = stems(text), set(re.findall(r"\d+(?:\.\d+)?|[a-z]+", text.lower()))
        turn_stems = [stems(t["text"]) for t in turns]

        def add(claim, label, etype, ev_turns, kind="full"):
            rows.append(dict(encounter_id=eid, claim=claim, label=label, error_type=etype, evidence=kind,
                             premise=turns_to_text(ev_turns)))

        supported = [s for s in pool[eid] if coverage(s, d_stems) >= a.min_coverage]
        rng.shuffle(supported)
        for s in supported[:a.supported]:
            add(s, "supported", "none", full_evidence(turns, s))

        by_type = {}
        for s in supported:
            for etype, new in perturb(s, d_words, rng):
                by_type.setdefault(etype, []).append((s, new))
        picked = []
        while len(picked) < a.contradicted and any(by_type.values()):  # round-robin keeps the types balanced
            for etype in sorted(by_type):
                if by_type[etype] and len(picked) < a.contradicted:
                    picked.append((etype, *by_type[etype].pop()))
        for etype, s, new in picked:
            add(new, "contradicted", etype, full_evidence(turns, s))

        others = [s for o, ss in pool.items() if o != eid for s in ss
                  if len(s.split()) >= 6 and coverage(s, d_stems) <= a.max_foreign_coverage]
        for s in rng.sample(others, min(a.unsupported, len(others))):
            add(s, "unsupported", "fabricated_symptom", full_evidence(turns, s))

        if split == "train":  # short evidence, as in feature grounding and top-k
            done = 0
            for s in supported:
                if done >= a.windows:
                    break
                best = max(range(len(turns)), key=lambda i: len(stems(s) & turn_stems[i]))
                near = turns[max(0, best - 2): best + 3]
                if coverage(s, stems(" ".join(t["text"] for t in near))) < 0.7:
                    continue
                far = [i for i in range(0, len(turns) - 4)
                       if abs(i + 2 - best) > 6 and coverage(s, set().union(*turn_stems[i:i + 5])) <= 0.2]
                add(s, "supported", "none", near, "window")
                if far:
                    i = rng.choice(far)
                    add(s, "unsupported", "none", turns[i:i + 5], "window")
                done += 1
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="train", choices=["train", "dev"])
    ap.add_argument("--supported", type=int, default=10, help="whole-dialogue pairs per encounter, per label")
    ap.add_argument("--contradicted", type=int, default=6)
    ap.add_argument("--unsupported", type=int, default=6)
    ap.add_argument("--windows", type=int, default=5, help="short-evidence sentence pairs per encounter (train)")
    ap.add_argument("--min-coverage", type=float, default=0.6)
    ap.add_argument("--max-foreign-coverage", type=float, default=0.34)
    a = ap.parse_args()

    rows = build(a.split, a)
    random.Random(C.SEED).shuffle(rows)
    if a.split == "train":
        path = C.DATA_DIR / "so_train.jsonl"
        write_jsonl(path, [dict(messages=entail_messages(r["premise"], r["claim"]), target=r["label"],
                                source=r["error_type"], evidence=r["evidence"], encounter_id=r["encounter_id"])
                           for r in rows])
    else:
        path = C.DATA_DIR / "s1_eval.jsonl"
        write_jsonl(path, [dict(id=f"{r['encounter_id']}_SO{i:04d}", premise=r["premise"], claim=r["claim"],
                                label=r["label"], error_type=r["error_type"], encounter_id=r["encounter_id"])
                           for i, r in enumerate(rows)])
    print(f"[{a.split}] {len(rows)} pairs from {len({r['encounter_id'] for r in rows})} encounters -> {path}")
    print("  label   :", dict(Counter(r["label"] for r in rows)))
    print("  type    :", dict(Counter(r["error_type"] for r in rows)))
    print("  evidence:", dict(Counter(r["evidence"] for r in rows)))
    seen = set()
    for r in rows:  # one sample per (label, type, evidence) to read before training
        k = (r["label"], r["error_type"], r["evidence"])
        if k not in seen:
            seen.add(k)
            print(f"  e.g. {k}: {r['claim']}")


if __name__ == "__main__":
    main()
