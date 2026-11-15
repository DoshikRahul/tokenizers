"""
Atomic Fact Decomposer for uMedSum Stage 2.
Decomposes complex/uncertain clinical sentences into atomic, standalone factual propositions.
As specified in paper Appendix A.6, uses the Stage 1 model (LLaMA 3 via Ollama).

Changes vs. previous version:
- Few-shot prompt so LLaMA 3 actually splits compound clinical sentences.
- Robust parsing (ignores "Here are the atomic facts:" preambles, dedupes, drops the unchanged input).
- If the LLM returns the sentence unsplit (or Ollama fails), a rule-based clause splitter is used,
  so a long compound sentence is never silently passed through undecomposed.
- `decompose_with_info()` reports which method produced the split (for logging/debugging).
"""

import json
import re
import urllib.request
from typing import List, Tuple

DECOMPOSITION_PROMPT = (
    "You are an expert NLP and clinical logic assistant.\n"
    "Decompose the clinical statement into independent, self-contained ATOMIC FACTS.\n"
    "An atomic fact is the smallest clause-level proposition that can stand alone as true or false.\n\n"
    "Rules:\n"
    "- Split every list, every conjunction (and / but / while / with) and every separate finding into its own fact.\n"
    "- Each fact must be self-contained (replace pronouns with the subject, e.g. 'The patient').\n"
    "- Do NOT add, infer or change any information that is not in the statement.\n"
    "- Only if the statement truly contains a single proposition, output that one fact.\n\n"
    "Example 1\n"
    "Statement: The patient reports chest pain and shortness of breath for two days, and denies fever.\n"
    "Atomic Facts:\n"
    "- The patient reports chest pain for two days.\n"
    "- The patient reports shortness of breath for two days.\n"
    "- The patient denies fever.\n\n"
    "Example 2\n"
    "Statement: Start lisinopril 10 mg daily and follow up in two weeks with a repeat blood pressure check.\n"
    "Atomic Facts:\n"
    "- Start lisinopril 10 mg daily.\n"
    "- Follow up in two weeks.\n"
    "- A repeat blood pressure check is planned at follow up.\n\n"
    "Now decompose this statement.\n"
    "Statement: {statement}\n"
    "Atomic Facts:"
)

_PREAMBLE_RE = re.compile(r"^(here (are|is)|atomic facts|the following|sure|okay|note:)", re.IGNORECASE)


class AtomicDecomposer:
    def __init__(self, ollama_url: str = "http://localhost:11434", model: str = "llama3:8b"):
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        self.last_method = "none"
        self.last_error = ""

    # ------------------------------------------------------------------ public API
    def decompose(self, sentence: str) -> List[str]:
        """Decompose a sentence into a list of atomic factual statements."""
        return self.decompose_with_info(sentence)[0]

    def decompose_with_info(self, sentence: str) -> Tuple[List[str], str]:
        """Returns (atomic_facts, method) where method in {'too_short','llm','rule_based','unsplit'}."""
        sentence = sentence.strip()
        self.last_error = ""
        if not sentence or len(sentence.split()) <= 4:
            self.last_method = "too_short"
            return [sentence], self.last_method

        facts = []
        try:
            facts = self._llm_decompose(sentence)
        except Exception as e:  # keep the reason instead of swallowing it
            self.last_error = str(e)

        if self._is_real_split(sentence, facts):
            self.last_method = "llm"
            return facts, self.last_method

        # LLM failed or returned the sentence unchanged -> rule-based clause split
        rule_facts = self.fallback_clause_split(sentence)
        if self._is_real_split(sentence, rule_facts):
            self.last_method = "rule_based"
            return rule_facts, self.last_method

        self.last_method = "unsplit"
        return [sentence], self.last_method

    # ------------------------------------------------------------------ internals
    def _llm_decompose(self, sentence: str) -> List[str]:
        payload = {
            "model": self.model,
            "prompt": DECOMPOSITION_PROMPT.format(statement=sentence),
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 400},
        }
        req = urllib.request.Request(
            f"{self.ollama_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = json.loads(resp.read().decode("utf-8")).get("response", "").strip()
        return self._parse_facts(raw)

    @staticmethod
    def _parse_facts(raw: str) -> List[str]:
        facts, seen = [], set()
        for line in raw.splitlines():
            line = line.strip()
            if not line or _PREAMBLE_RE.match(line):
                continue
            cleaned = re.sub(r"^(?:[-*\u2022]+|\d+[.)])\s*", "", line).strip()
            cleaned = cleaned.replace("**", "").strip()
            if len(cleaned.split()) < 2:
                continue
            key = cleaned.lower().rstrip(".")
            if key not in seen:
                seen.add(key)
                facts.append(cleaned)
        return facts

    @staticmethod
    def _is_real_split(sentence: str, facts: List[str]) -> bool:
        """True if facts contain >1 distinct unit, or a single unit that differs from the input."""
        if not facts:
            return False
        if len(facts) > 1:
            return True
        norm = lambda s: re.sub(r"\W+", " ", s.lower()).strip()
        return norm(facts[0]) != norm(sentence)

    @staticmethod
    def fallback_clause_split(sentence: str) -> List[str]:
        """Rule-based clause splitting used when the LLM does not split the sentence."""
        parts = re.split(
            r";\s*|,\s*(?:and|but|while|whereas|which|with|as well as)\s+|\s+(?:and|but|while|whereas)\s+|,\s+",
            sentence,
            flags=re.IGNORECASE,
        )
        cleaned = [p.strip(" .,") for p in parts if p and len(p.strip().split()) >= 3]
        cleaned = [c if c.endswith(".") else c + "." for c in cleaned]
        return cleaned if len(cleaned) > 1 else [sentence]