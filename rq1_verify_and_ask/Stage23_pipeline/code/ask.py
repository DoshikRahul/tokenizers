"""Stage 3b - Ask: identify unresolved, clinically relevant gaps and generate targeted questions.

No answers exist in the current data, so unanswered gaps are stored as `unresolved`; nothing is
invented. If a follow-up answers file is supplied, an answer is converted to a statement only if it is
entailed by the answer text itself, and it is kept in a separate list (source = follow_up).
"""
from typing import Dict, List, Optional

GAP_SYSTEM = "You are a careful clinician reviewing a draft note for missing information."
GAP_PROMPT = (
    "Below are a doctor-patient conversation and the draft Subjective/Objective note.\n\n"
    "CONVERSATION:\n{dialogue}\n\nDRAFT NOTE:\n{note}\n\n"
    "List clinically relevant Subjective/Objective details for THIS visit that are NOT established anywhere "
    "in the conversation (for example an unasked symptom, duration, severity, allergy, medication dose, "
    "or a missing measurement). Do NOT guess answers. Do NOT list anything the conversation already answers. "
    "At most {k} items, most important first.\n"
    'Return JSON: {{"gaps": [{{"gap": "<what is unknown>", "question": "<one targeted question to ask>", '
    '"category": "subjective|objective"}}]}}'
)
ANSWERED_SYSTEM = "You check whether a question is already answered by a conversation."
ANSWERED_PROMPT = (
    "CONVERSATION:\n{dialogue}\n\nQUESTION: {question}\n\n"
    "Is this question already answered in the conversation? Answer with exactly one word: yes or no."
)
ANSWER_SYSTEM = "You convert a patient's follow-up answer into a note statement."
ANSWER_PROMPT = (
    "Question: {question}\nPatient answer: {answer}\n\n"
    "Write ONE standalone third-person note sentence stating exactly what the answer says. "
    "Use only the answer. If the answer gives no usable information, reply exactly: NONE\nSentence:"
)


class GapQuestioner:
    def __init__(self, llm, embedder, max_questions: int):
        self.llm, self.embedder, self.max_questions = llm, embedder, max_questions

    def find_gaps(self, dialogue: str, note_text: str) -> Dict:
        try:
            data = self.llm.chat_json(GAP_SYSTEM, GAP_PROMPT.format(
                dialogue=dialogue, note=note_text, k=self.max_questions), num_predict=700)
        except Exception as exc:
            return {"gaps": [], "dropped": [], "error": f"{type(exc).__name__}: {exc}"}
        items = data.get("gaps", []) if isinstance(data, dict) else (data or [])
        gaps, dropped, seen = [], [], []
        for it in items:
            if not isinstance(it, dict) or not it.get("question"):
                continue
            q = it["question"].strip()
            redundant_with = self._similar(q, seen)
            if redundant_with:
                dropped.append({**it, "status": "dropped_duplicate_question", "similar_to": redundant_with})
                continue
            if self._answered(dialogue, q):
                dropped.append({**it, "status": "dropped_already_answered"})
                continue
            seen.append(q)
            gaps.append({"id": f"q{len(gaps) + 1}", "gap": it.get("gap", ""), "question": q,
                         "category": it.get("category", ""), "status": "unresolved", "answer": None})
        return {"gaps": gaps[: self.max_questions], "dropped": dropped, "num_generated": len(items)}

    def _answered(self, dialogue: str, question: str) -> bool:
        try:
            out = self.llm.chat(ANSWERED_SYSTEM, ANSWERED_PROMPT.format(dialogue=dialogue, question=question),
                                num_predict=3).lower()
        except Exception:
            return False
        return out.startswith("yes")

    def _similar(self, q: str, previous: List[str], thr: float = 0.9) -> Optional[str]:
        if not previous:
            return None
        e = self.embedder.encode([q] + previous, convert_to_numpy=True, normalize_embeddings=True)
        sims = e[1:] @ e[0]
        i = int(sims.argmax())
        return previous[i] if float(sims[i]) >= thr else None

    def apply_answers(self, gaps: List[Dict], answers: Dict[str, str], nli) -> List[Dict]:
        """Attach recorded follow-up answers (keyed by gap id). Unanswered gaps stay `unresolved`."""
        for g in gaps:
            ans = (answers or {}).get(g["id"])
            if not ans:
                continue
            g["answer"] = ans
            try:
                stmt = self.llm.chat(ANSWER_SYSTEM, ANSWER_PROMPT.format(question=g["question"], answer=ans),
                                     num_predict=100).strip()
            except Exception:
                stmt = ""
            if stmt and not stmt.upper().startswith("NONE") and \
                    nli.score(f"Patient: {ans}", stmt)["entailment"] >= 0.8:
                g["status"], g["answer_statement"] = "resolved", stmt
            else:
                g["status"] = "answer_unusable"
        return gaps
