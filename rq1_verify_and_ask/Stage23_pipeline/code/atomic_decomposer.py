"""Atomic claim decomposition (LLM with rule-based fallback).

Adapted from the uMedSum baseline decomposer; uses the shared LLMClient.
"""
import re
from typing import List, Tuple

from common import norm

SYSTEM = "You are an expert NLP and clinical logic assistant."

PROMPT = (
    "Decompose the clinical statement into independent, self-contained ATOMIC FACTS.\n"
    "An atomic fact is the smallest clause-level proposition that can stand alone as true or false.\n\n"
    "Rules:\n"
    "- Split every list, every conjunction (and / but / while / with) and every separate finding into its own fact.\n"
    "- Each fact must be self-contained (replace pronouns with the subject, e.g. 'The patient').\n"
    "- Keep negations and denials exactly as stated (e.g. 'denies fever').\n"
    "- Do NOT add, infer or change any information that is not in the statement.\n"
    "- If the statement contains a single proposition, output that one fact.\n\n"
    "Example\n"
    "Statement: The patient reports chest pain and shortness of breath for two days, and denies fever.\n"
    "Atomic Facts:\n"
    "- The patient reports chest pain for two days.\n"
    "- The patient reports shortness of breath for two days.\n"
    "- The patient denies fever.\n\n"
    "Example with a denial list (every fact keeps its negation)\n"
    "Statement: He reports no other symptoms such as frequent urination, increased thirst, or weight loss.\n"
    "Atomic Facts:\n"
    "- The patient denies frequent urination.\n"
    "- The patient denies increased thirst.\n"
    "- The patient denies weight loss.\n\n"
    "Do not add explanations, hedges or parenthetical remarks. Do not change who does what or how often.\n\n"
    "Now decompose this statement. Output only the list.\n"
    "Statement: {statement}\n"
    "Atomic Facts:"
)

_PREAMBLE = re.compile(r"^(here (are|is)|atomic facts|the following|sure|okay|note:)", re.IGNORECASE)


class AtomicDecomposer:
    def __init__(self, llm):
        self.llm = llm
        self.last_method = "none"

    def decompose(self, sentence: str) -> List[str]:
        return self.decompose_with_info(sentence)[0]

    def decompose_with_info(self, sentence: str) -> Tuple[List[str], str]:
        sentence = sentence.strip()
        if not sentence or len(sentence.split()) <= 4:
            self.last_method = "too_short"
            return [sentence], self.last_method
        facts = []
        try:
            facts = self._parse(self.llm.chat(SYSTEM, PROMPT.format(statement=sentence), num_predict=400))
        except Exception:
            pass
        if self._is_split(sentence, facts):
            self.last_method = "llm"
            return facts, self.last_method
        rule = self.clause_split(sentence)
        if self._is_split(sentence, rule):
            self.last_method = "rule_based"
            return rule, self.last_method
        self.last_method = "unsplit"
        return [sentence], self.last_method

    @staticmethod
    def _parse(raw: str) -> List[str]:
        facts, seen = [], set()
        for line in raw.splitlines():
            line = line.strip()
            if not line or _PREAMBLE.match(line):
                continue
            cleaned = re.sub(r"^(?:[-*•]+|\d+[.)])\s*", "", line).replace("**", "").strip()
            if len(cleaned.split()) < 2 or norm(cleaned) in seen:
                continue
            seen.add(norm(cleaned))
            facts.append(cleaned)
        return facts

    @staticmethod
    def _is_split(sentence: str, facts: List[str]) -> bool:
        if not facts:
            return False
        return len(facts) > 1 or norm(facts[0]) != norm(sentence)

    @staticmethod
    def clause_split(sentence: str) -> List[str]:
        parts = re.split(
            r";\s*|,\s*(?:and|but|while|whereas|which|with|as well as)\s+|\s+(?:and|but|while|whereas)\s+|,\s+",
            sentence, flags=re.IGNORECASE)
        cleaned = [p.strip(" .,") for p in parts if p and len(p.strip().split()) >= 3]
        cleaned = [c if c.endswith(".") else c + "." for c in cleaned]
        return cleaned if len(cleaned) > 1 else [sentence]
