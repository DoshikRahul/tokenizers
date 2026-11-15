"""DeBERTa NLI scorer: premise (dialogue or note) vs hypothesis (claim).

Adapted from the uMedSum baseline scorer. Differences:
- premise is chunked on turn/line boundaries (with overlap) so speaker context is not cut mid-turn;
- returns separate evidence for support (best entailing chunk) and for contradiction (best contradicting chunk).
"""
import re
from typing import Dict, List

from config import NLI_MODEL


class NLIScorer:
    def __init__(self, model_name: str = NLI_MODEL, device: str = None,
                 max_premise_tokens: int = 380, overlap_lines: int = 2):
        import torch
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name).to(self.device).eval()
        self.max_premise_tokens, self.overlap_lines = max_premise_tokens, overlap_lines
        self.entail_idx, self.neutral_idx, self.contra_idx = 0, 1, 2
        for idx, label in self.model.config.id2label.items():
            label = label.lower()
            if "entail" in label:
                self.entail_idx = idx
            elif "contra" in label:
                self.contra_idx = idx
            elif "neut" in label:
                self.neutral_idx = idx
        self._chunk_cache: Dict[str, List[str]] = {}

    def chunk(self, premise: str) -> List[str]:
        if premise in self._chunk_cache:
            return self._chunk_cache[premise]
        lines = [l for l in premise.splitlines() if l.strip()]
        sizes = [len(self.tokenizer.tokenize(l)) for l in lines]
        chunks, start = [], 0
        while start < len(lines):
            end, total = start, 0
            while end < len(lines) and (total + sizes[end] <= self.max_premise_tokens or end == start):
                total += sizes[end]
                end += 1
            chunks.append("\n".join(lines[start:end]))
            if end >= len(lines):
                break
            start = max(end - self.overlap_lines, start + 1)
        chunks = chunks or [premise]
        if len(self._chunk_cache) > 256:
            self._chunk_cache.clear()
        self._chunk_cache[premise] = chunks
        return chunks

    @staticmethod
    def best_line(chunk: str, hypothesis: str) -> str:
        lines = [l.strip() for l in chunk.splitlines() if len(l.split()) >= 3] or [chunk[:200]]
        hyp = set(re.findall(r"\w+", hypothesis.lower()))
        return max(lines, key=lambda l: len(hyp & set(re.findall(r"\w+", l.lower()))))

    def score(self, premise: str, hypothesis: str) -> Dict:
        """Max-pool entailment and contradiction over premise chunks."""
        torch = self.torch
        chunks = self.chunk(premise)
        with torch.no_grad():
            enc = self.tokenizer(chunks, [hypothesis] * len(chunks), truncation="only_first",
                                 max_length=512, padding=True, return_tensors="pt").to(self.device)
            probs = torch.softmax(self.model(**enc).logits, dim=-1)
        e_idx = int(torch.argmax(probs[:, self.entail_idx]))
        c_idx = int(torch.argmax(probs[:, self.contra_idx]))
        return {
            "entailment": float(probs[e_idx, self.entail_idx]),
            "neutral": float(probs[e_idx, self.neutral_idx]),
            "contradiction": float(probs[c_idx, self.contra_idx]),
            "support_evidence": self.best_line(chunks[e_idx], hypothesis),
            "contradiction_evidence": self.best_line(chunks[c_idx], hypothesis),
        }
