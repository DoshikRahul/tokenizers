"""Integrated Stage 2-3 controller.

Modules, run in order for each case:
  Verification (verification.py)  ->  Omission + validation + insertion (omission.py)
  ->  Ask (ask.py)  ->  Finalizer (this file).
The ground-truth note is never passed to any of them; A/P from Stage 1 is carried through unchanged.
"""
import config as C


class Stage23Controller:
    def __init__(self, enable_ask: bool = True, use_gpt2_placement: bool = True, stage2_only: bool = False):
        from llm_client import LLMClient
        from nli_remote import make_nli_scorer
        from atomic_decomposer import AtomicDecomposer
        from verification import ClaimVerifier
        from omission import OmissionDetector
        from ask import GapQuestioner

        self.llm = LLMClient()
        self.nli = make_nli_scorer()
        self.stage2_only = stage2_only
        self.decomposer = AtomicDecomposer(self.llm)
        self.verifier = ClaimVerifier(self.nli, self.decomposer, self.llm, C.TE, C.TA, C.TCONTRA,
                                      C.UNSUPPORTED_POLICY, C.CORRECT_CONTRADICTIONS)
        if stage2_only:  # no MiniLM / GPT-2 loaded
            self.embedder = self.omission = self.questioner = None
            return
        from embed_remote import make_embedder
        self.embedder = make_embedder()
        if use_gpt2_placement:
            from perplexity_merger import PerplexityPlacer
            placer = PerplexityPlacer()
        else:
            from perplexity_merger import AppendPlacer
            placer = AppendPlacer()
        self.omission = OmissionDetector(self.embedder, self.nli, self.llm, placer, C.COV_MIN, C.MAX_CANDIDATES,
                                         C.ADD_ENTAIL_MIN, C.ADD_CONTRA_MAX, C.DUP_ENTAIL_MIN, C.DUP_SIM_MIN)
        self.questioner = GapQuestioner(self.llm, self.embedder, C.MAX_QUESTIONS) if enable_ask else None

    def run_case(self, rec: dict, answers: dict = None) -> dict:
        """`rec` is one Stage 1 record (uses only conversation, stage1_so, stage1_ap)."""
        dialogue = rec["conversation"]
        stage1_so = {k: rec["stage1_so"].get(k, "") for k in ("subjective", "objective")}

        # Stage 2: verify existing claims
        prior = rec.get("_stage2")  # saved Stage 2 result to reuse (run_stage23.py --reuse-stage2)
        if prior:
            ver = {"so": prior["stage2_so"], "audit": prior["stage2_audit"], "stats": prior["stage2_stats"]}
        else:
            ver = self.verifier.verify_so(dialogue, stage1_so)

        if self.stage2_only:
            return {
                "case_id": rec["case_id"], "split": rec.get("split"),
                "stage1_so": stage1_so, "stage2_so": ver["so"], "stage1_ap": rec["stage1_ap"],
                "stage2_audit": ver["audit"], "stage2_stats": ver["stats"],
                "unsupported_claims": self.collect_unsupported(ver["audit"], []),
                "thresholds": {"TE": C.TE, "TA": C.TA, "TCONTRA": C.TCONTRA,
                               "UNSUPPORTED_POLICY": C.UNSUPPORTED_POLICY},
            }

        # Stage 3a: omissions -> validated additions
        om = self.omission.run(dialogue, ver["so"])

        # Stage 3b: unresolved gaps -> questions (no invented answers)
        gaps = {"gaps": [], "dropped": []}
        if self.questioner:
            note_text = "\n\n".join(f"{k.capitalize()}:\n{om['so'][k]}" for k in om["so"])
            gaps = self.questioner.find_gaps(dialogue, note_text)
            if answers:
                self.questioner.apply_answers(gaps["gaps"], answers, self.nli)

        unsupported = self.collect_unsupported(ver["audit"], om["candidate_log"])
        return {
            "case_id": rec["case_id"],
            "split": rec.get("split"),
            "stage1_so": stage1_so,
            "stage2_so": ver["so"],
            "stage3_so": om["so"],
            "stage1_ap": rec["stage1_ap"],          # unchanged A/P, outside the RQ1 intervention
            "stage2_audit": ver["audit"],
            "stage2_stats": ver["stats"],
            "stage3_added": om["added"],
            "stage3_candidate_log": om["candidate_log"],
            "stage3_stats": om["stats"],
            "gaps": gaps,
            "unsupported_claims": unsupported,
            "thresholds": {"TE": C.TE, "TA": C.TA, "TCONTRA": C.TCONTRA, "COV_MIN": C.COV_MIN,
                           "UNSUPPORTED_POLICY": C.UNSUPPORTED_POLICY},
        }

    @staticmethod
    def collect_unsupported(audit: list, candidate_log: list) -> dict:
        """Everything kept OUT of the note, with reasons, so it can be reviewed instead of lost."""
        stage2 = [
            {"stage": "stage2", "section": a["section"], "claim": a["claim"], "source_sentence": a["sentence"],
             "decision": a["decision"], "scores": a["scores"], "reason": a["reason"],
             "nearest_evidence": a["contradiction_evidence"] if a["decision"] == "removed_contradicted"
             else a["support_evidence"]}
            for a in audit if a["decision"] in ("removed_unsupported", "removed_contradicted")
        ]
        flagged = [  # kept in the note but flagged for review (uncertain / unsupported_flagged)
            {"stage": "stage2", "section": a["section"], "claim": a["claim"], "decision": a["decision"],
             "scores": a["scores"], "reason": a["reason"]}
            for a in audit if a["decision"] in ("uncertain", "unsupported_flagged")
        ]
        stage3 = [
            {"stage": "stage3", "candidate": c["candidate"], "statement": c.get("statement", ""),
             "decision": c["status"], "scores": c.get("scores_vs_dialogue"), "reason": c["reason"]}
            for c in candidate_log if c["status"] == "rejected_unsupported"
        ]
        return {"removed_stage2": stage2, "flagged_kept_stage2": flagged, "rejected_stage3": stage3}
