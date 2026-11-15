"""Stage 3a - omission detection, evidence validation and safe insertion.

1. Candidates: statements from the conversation (patient answers + doctor declaratives; questions excluded).
2. Coverage: max MiniLM similarity of each candidate to the verified S/O sentences. Low coverage
   (<= COV_MIN) only makes it a *possible* omission.
3. Validation (explicit): the candidate is rewritten into a standalone statement, which must be
   (a) entailed by the conversation, (b) not contradicted, (c) not already represented in the S/O.
4. Insertion: only validated statements are inserted, placed by GPT-2 perplexity (fluency only).
The ground-truth note is never an input.
"""
import re
from typing import Dict, List

import numpy as np

import config as C
from common import is_question, parse_turns, split_sentences, strip_bullet, is_placeholder

# Whole-section placeholder written by Stage 1 when nothing was documented. It must go once a real
# finding is added to that section, otherwise the note would contradict itself.
_SECTION_PLACEHOLDER = re.compile(r"no objective clinical|were documented in the conversation", re.IGNORECASE)

REWRITE_SYSTEM = "You convert conversation statements into standalone clinical note statements."
REWRITE_PROMPT = (
    "Doctor's preceding question (context only): {context}\n"
    "Statement from the conversation: {statement}\n\n"
    "Write ONE short, standalone third-person clinical note sentence that states exactly what the "
    "statement says (e.g. 'The patient reports ...' / 'The patient denies ...'). Use only information in "
    "the statement and the question context. Do not add, infer or generalise anything: no interpretation "
    "(such as 'consistent with'), no extra details, and no claims about what was NOT done or NOT reported "
    "unless the statement says so.\n"
    "If the statement is not clinically relevant (greeting, filler, scheduling, a fragment with no clinical "
    "content), reply exactly: NONE\n"
    "Sentence:"
)
# Second attempt after a rewrite was not entailed by the conversation: stay as close to the words as possible.
STRICT_REWRITE_PROMPT = (
    "Doctor's preceding question (context only): {context}\n"
    "Statement from the conversation: {statement}\n"
    "A previous rewrite contained information that is not in the statement: {previous}\n\n"
    "Write ONE short third-person sentence that reuses the statement's own words as closely as possible "
    "('The patient reports ...', 'The patient states ...'). Include only what the statement itself says. "
    "If it cannot be done, reply exactly: NONE\nSentence:"
)
SECTION_SYSTEM = "You classify clinical note sentences."
SECTION_PROMPT = (
    "Is this sentence Subjective (patient-reported symptoms, history, concerns, medications, lifestyle) or "
    "Objective (vital signs, measurements, clinician-observed examination findings, lab/imaging results)?\n"
    "Sentence: {sentence}\nAnswer with exactly one word: Subjective or Objective."
)


class OmissionDetector:
    def __init__(self, embedder, nli, llm, placer, cov_min, max_candidates,
                 add_entail_min, add_contra_max, dup_entail_min, dup_sim_min):
        self.embedder, self.nli, self.llm, self.placer = embedder, nli, llm, placer
        self.cov_min, self.max_candidates = cov_min, max_candidates
        self.add_entail_min, self.add_contra_max = add_entail_min, add_contra_max
        self.dup_entail_min, self.dup_sim_min = dup_entail_min, dup_sim_min

    # ------------------------------------------------------------------ 1. candidates
    @staticmethod
    def extract_candidates(dialogue: str) -> List[Dict]:
        cands, last_doctor = [], ""
        for speaker, text in parse_turns(dialogue):
            if speaker == "Doctor":
                last_doctor = text
            if speaker not in C.CANDIDATE_SPEAKERS:  # default: patient statements only
                continue
            for sent in split_sentences(text):
                if is_question(sent) or len(sent.split()) < 2:
                    continue
                if speaker == "Doctor" and len(sent.split()) < 5:
                    continue
                cands.append({"text": sent, "speaker": speaker,
                              "context": last_doctor if speaker == "Patient" else ""})
        return cands

    # ------------------------------------------------------------------ 2. coverage
    def so_sentences(self, so: Dict) -> List[str]:
        out = []
        for key in ("subjective", "objective"):
            for line in (so.get(key) or "").splitlines():
                if line.strip():
                    out += [s for s in split_sentences(strip_bullet(line)[1]) if not is_placeholder(s)]
        return out

    def score_coverage(self, cands: List[Dict], so_sents: List[str]) -> None:
        if not cands:
            return
        if not so_sents:
            for c in cands:
                c["coverage"] = 0.0
                c["nearest_so_sentence"] = ""
            return
        c_emb = self.embedder.encode([c["text"] for c in cands], convert_to_numpy=True, normalize_embeddings=True)
        s_emb = self.embedder.encode(so_sents, convert_to_numpy=True, normalize_embeddings=True)
        sim = c_emb @ s_emb.T
        for i, c in enumerate(cands):
            j = int(np.argmax(sim[i]))
            c["coverage"] = round(float(sim[i, j]), 4)
            c["nearest_so_sentence"] = so_sents[j]

    # ------------------------------------------------------------------ 3. validation
    def rewrite(self, cand: Dict, previous: str = "") -> str:
        try:
            prompt = (STRICT_REWRITE_PROMPT.format(context=cand["context"] or "(none)", statement=cand["text"],
                                                   previous=previous)
                      if previous else
                      REWRITE_PROMPT.format(context=cand["context"] or "(none)", statement=cand["text"]))
            out = self.llm.chat(REWRITE_SYSTEM, prompt, num_predict=100).strip().strip('"')
        except Exception:
            return ""
        return "" if (not out or out.upper().startswith("NONE") or "\n" in out) else out

    def validate(self, dialogue: str, so_text: str, so_sents: List[str], cand: Dict) -> Dict:
        rec = {"candidate": cand["text"], "speaker": cand["speaker"], "coverage": cand["coverage"],
               "nearest_so_sentence": cand["nearest_so_sentence"], "statement": "", "status": "", "reason": ""}
        stmt = self.rewrite(cand)
        if not stmt:
            rec.update(status="rejected_not_clinical", reason="No standalone clinical statement (filler/fragment).")
            return rec
        rec["statement"] = stmt
        s = self.nli.score(dialogue, stmt)
        rec["evidence"] = s["support_evidence"]
        rec["scores_vs_dialogue"] = {"entailment": round(s["entailment"], 4),
                                     "contradiction": round(s["contradiction"], 4)}
        if s["entailment"] < self.add_entail_min or s["contradiction"] > self.add_contra_max:
            # The rewrite probably added something; try once more, staying close to the patient's own words.
            retry = self.rewrite(cand, previous=stmt)
            if retry and retry != stmt:
                s2 = self.nli.score(dialogue, retry)
                if s2["entailment"] >= self.add_entail_min and s2["contradiction"] <= self.add_contra_max:
                    rec["first_rewrite_rejected"] = stmt
                    stmt, s = retry, s2
                    rec["statement"], rec["evidence"] = stmt, s["support_evidence"]
                    rec["scores_vs_dialogue"] = {"entailment": round(s["entailment"], 4),
                                                 "contradiction": round(s["contradiction"], 4)}
        if s["entailment"] < self.add_entail_min or s["contradiction"] > self.add_contra_max:
            rec.update(status="rejected_unsupported", reason="Rewritten statement is not entailed by the conversation.")
            return rec
        d = self.nli.score(so_text, stmt) if so_text.strip() else {"entailment": 0.0}
        rec["duplicate_entailment"] = round(d["entailment"], 4)
        sim = self._max_sim(stmt, so_sents)
        rec["duplicate_similarity"] = round(sim, 4)
        if d["entailment"] >= self.dup_entail_min or sim >= self.dup_sim_min:
            rec.update(status="rejected_duplicate", reason="Already represented in the verified S/O.")
            return rec
        rec.update(status="validated", reason="Supported by the conversation and not already in the S/O.")
        return rec

    def _max_sim(self, stmt: str, so_sents: List[str]) -> float:
        if not so_sents:
            return 0.0
        e = self.embedder.encode([stmt] + so_sents, convert_to_numpy=True, normalize_embeddings=True)
        return float(np.max(e[1:] @ e[0]))

    # ------------------------------------------------------------------ 4. insertion
    def assign_section(self, stmt: str) -> str:
        try:
            out = self.llm.chat(SECTION_SYSTEM, SECTION_PROMPT.format(sentence=stmt), num_predict=5).lower()
        except Exception:
            return "subjective"
        return "objective" if "objective" in out else "subjective"

    def insert(self, so: Dict, section: str, statement: str) -> Dict:
        lines = [l for l in (so.get(section) or "").splitlines() if l.strip()]
        dropped = [l for l in lines if _SECTION_PLACEHOLDER.search(l)]
        lines = [l for l in lines if l not in dropped]  # a real finding replaces "nothing documented"
        loc, ppl = self.placer.best_position(lines, "* " + statement)
        lines.insert(loc, "* " + statement)
        so[section] = "\n".join(lines)
        return {"section": section, "line_index": loc, "perplexity": None if ppl != ppl else round(ppl, 2),
                "removed_placeholder": [l.strip() for l in dropped]}

    # ------------------------------------------------------------------ driver
    def run(self, dialogue: str, verified_so: Dict) -> Dict:
        so = {k: verified_so.get(k, "") for k in ("subjective", "objective")}
        so_text = "\n".join(f"{k}:\n{so[k]}" for k in so)
        so_sents = self.so_sentences(so)
        cands = self.extract_candidates(dialogue)
        self.score_coverage(cands, so_sents)
        covered = [c for c in cands if c["coverage"] > self.cov_min]
        flagged = sorted((c for c in cands if c["coverage"] <= self.cov_min), key=lambda c: c["coverage"])
        overflow, flagged = flagged[self.max_candidates:], flagged[: self.max_candidates]

        # Phase 1: validate all flagged candidates concurrently against the verified note (rewrite + NLI calls
        # are independent and are the slow part). Phase 2 adds them one at a time and checks them against
        # each other, so the result is still deterministic in candidate order.
        from concurrent.futures import ThreadPoolExecutor
        so_sents_initial = list(so_sents)
        with ThreadPoolExecutor(max_workers=4) as ex:
            recs = list(ex.map(lambda c: self.validate(dialogue, so_text, so_sents_initial, c), flagged))

        log, added = [], []
        for rec in recs:
            if rec["status"] == "validated":
                stmt = rec["statement"]
                added_texts = [a["statement"] for a in added]
                dup = bool(added_texts) and (
                    stmt.lower().rstrip(".") in {t.lower().rstrip(".") for t in added_texts}
                    or self._max_sim(stmt, added_texts) >= self.dup_sim_min
                    or self.nli.score("\n".join(added_texts), stmt)["entailment"] >= self.dup_entail_min)
                if dup:
                    rec.update(status="rejected_duplicate", reason="Duplicate of another added statement.")
                else:
                    section = self.assign_section(stmt)
                    rec["insertion"] = self.insert(so, section, stmt)
                    added.append({"statement": stmt, "evidence": rec["evidence"],
                                  "section": section, "candidate": rec["candidate"]})
            log.append(rec)
        return {
            "so": so,
            "added": added,
            "candidate_log": log,
            "stats": {"num_candidates": len(cands), "num_covered": len(covered), "num_flagged": len(flagged),
                      "num_not_checked_cap": len(overflow), "num_added": len(added)},
        }
