"""Stage 2 - claim-level verification of the Stage 1 S/O against the conversation.

Pipeline per S/O line: sentence split -> atomic decomposition -> NLI against the dialogue -> decision.
The ground-truth note is never an input. A/P is not touched here.

Decisions (thresholds in config.py):
  supported        E >= TE                      keep
  uncertain        TA <= E < TE (not contradicted)  keep, flagged for review
  contradicted     C >= TCONTRA and E < TE      correct only if the dialogue evidence supports a rewrite, else remove
  unsupported      E < TA, not contradicted     remove (or keep+flag, per UNSUPPORTED_POLICY); never "proved false"
  exempt           'Not specified' style placeholders (statements of absence, not claims)
"""
import re
from collections import Counter
from typing import Dict, List

from common import is_placeholder, split_sentences, strip_bullet

CORRECT_SYSTEM = "You correct clinical note claims using only the evidence given."
CORRECT_PROMPT = (
    "A note claim conflicts with the conversation.\n"
    "Claim: {claim}\n"
    "Conversation evidence: {evidence}\n\n"
    "Rewrite the claim so it matches the evidence, using ONLY facts in the evidence "
    "(e.g. turn a wrongly asserted symptom into a denial). Do not add anything else. "
    "If the evidence does not let you state a correct version, reply exactly: NONE\n"
    "Corrected claim:"
)


class ClaimVerifier:
    def __init__(self, nli, decomposer, llm, te: float, ta: float, tcontra: float,
                 unsupported_policy: str = "remove", correct_contradictions: bool = True):
        self.nli, self.decomposer, self.llm = nli, decomposer, llm
        self.te, self.ta, self.tcontra = te, ta, tcontra
        self.policy, self.correct = unsupported_policy, correct_contradictions

    # ------------------------------------------------------------------ claim extraction (also used by evaluation)
    def claims_in_text(self, text: str) -> List[Dict]:
        """Atomic claims of a section, with their line index. Placeholders are skipped."""
        claims = []
        for li, raw in enumerate(text.splitlines()):
            if not raw.strip():
                continue
            _, body = strip_bullet(raw)
            for sent in split_sentences(body):
                if is_placeholder(sent):
                    continue
                for atom in self.decomposer.decompose(sent):
                    claims.append({"line": li, "sentence": sent, "claim": atom})
        return claims

    # ------------------------------------------------------------------ decision for one claim
    def decide(self, dialogue: str, claim: str, allow_correct: bool = True) -> Dict:
        s = self.nli.score(dialogue, claim)
        e, c = s["entailment"], s["contradiction"]
        rec = {
            "claim": claim,
            "scores": {"entailment": round(e, 4), "neutral": round(s["neutral"], 4), "contradiction": round(c, 4)},
            "support_evidence": s["support_evidence"],
            "contradiction_evidence": s["contradiction_evidence"],
            "corrected_text": None,
            "flagged": False,
        }
        if e >= self.te:
            rec.update(decision="supported", keep=True, output=claim,
                       reason="Entailed by the conversation.")
        elif c >= self.tcontra:
            fixed = self._correct(claim, s["contradiction_evidence"]) if (self.correct and allow_correct) else None
            if fixed:
                rec.update(decision="corrected", keep=True, output=fixed, corrected_text=fixed,
                           reason="Contradicted by the conversation; rewritten from the cited evidence.")
            else:
                rec.update(decision="removed_contradicted", keep=False, output="",
                           reason="Contradicted by the conversation and no evidence-based correction was possible.")
        elif e >= self.ta:
            rec.update(decision="uncertain", keep=True, output=claim, flagged=True,
                       reason="Partially supported; kept and flagged for review (neutral is not proof of falsehood).")
        elif self.policy == "flag":
            rec.update(decision="unsupported_flagged", keep=True, output=claim, flagged=True,
                       reason="No supporting evidence in the conversation; kept but flagged.")
        else:
            rec.update(decision="removed_unsupported", keep=False, output="",
                       reason="No supporting evidence in the conversation (not asserted to be false).")
        return rec

    def _correct(self, claim: str, evidence: str):
        try:
            out = self.llm.chat(CORRECT_SYSTEM, CORRECT_PROMPT.format(claim=claim, evidence=evidence),
                                num_predict=120).strip().strip('"')
        except Exception:
            return None
        out = re.sub(r"^(corrected claim|corrected|claim|sentence)\s*:\s*", "", out, flags=re.IGNORECASE).strip().strip('"')
        if not out or out.upper().startswith("NONE") or "\n" in out:
            return None
        return out if self._acceptable_correction(out) else None

    def _acceptable_correction(self, fixed: str) -> bool:
        # re-verified later against the full dialogue in verify_section via self._current_dialogue
        s = self.nli.score(self._current_dialogue, fixed)
        return s["entailment"] >= self.te and s["contradiction"] < self.tcontra

    # ------------------------------------------------------------------ section / S-O level
    def verify_section(self, dialogue: str, section: str, text: str) -> Dict:
        self._current_dialogue = dialogue
        out_lines, audit = [], []
        for li, raw in enumerate(text.splitlines()):
            if not raw.strip():
                out_lines.append(raw)
                continue
            marker, body = strip_bullet(raw)
            kept_parts = []
            for sent in split_sentences(body):
                if is_placeholder(sent):
                    kept_parts.append(sent)
                    audit.append({"section": section, "line": li, "sentence": sent, "claim": sent,
                                  "decision": "exempt", "keep": True, "flagged": False,
                                  "reason": "Placeholder / statement of absence; not verified as a claim."})
                    continue
                # Sentence first: a fully supported sentence is kept verbatim, with no decomposition,
                # so splitting errors (lost negations, invented atoms) cannot damage supported text.
                whole = self.decide(dialogue, sent, allow_correct=False)
                if whole["decision"] == "supported":
                    whole.update(section=section, line=li, sentence=sent, level="sentence")
                    audit.append(whole)
                    kept_parts.append(sent)
                    continue
                atoms = self.decomposer.decompose(sent)
                recs = [self.decide(dialogue, a) for a in atoms]
                for r in recs:
                    r.update(section=section, line=li, sentence=sent)
                audit.extend(recs)
                if all(r["keep"] and r["output"] == r["claim"] for r in recs):
                    kept_parts.append(sent)  # untouched sentence keeps its original wording
                else:
                    kept_parts.extend(r["output"] for r in recs if r["keep"])
            if kept_parts:
                out_lines.append(marker + " ".join(kept_parts))
        return {"text": "\n".join(out_lines).strip(), "audit": audit}

    def verify_so(self, dialogue: str, so: Dict) -> Dict:
        """Verify Subjective and Objective separately; section structure is preserved."""
        result, audit = {}, []
        for section in ("subjective", "objective"):
            r = self.verify_section(dialogue, section, so.get(section) or "")
            result[section] = r["text"]
            audit.extend(r["audit"])
        counts = Counter(a["decision"] for a in audit)
        verifiable = [a for a in audit if a["decision"] != "exempt"]
        kept = [a for a in verifiable if a["keep"]]
        stats = {
            "decision_counts": dict(counts),
            "num_claims": len(verifiable),
            "num_kept": len(kept),
            "claim_retention_rate": round(len(kept) / len(verifiable), 4) if verifiable else None,
        }
        return {"so": result, "audit": audit, "stats": stats}
