"""DeBERTa NLI scorer for U1 (same model and chunked max-pooling as the S/O pipeline and the uMedSum
baseline). Remote mode talks to the team's existing /nli server (NLI_BASE_URL, X-API-Key)."""
from typing import Dict, List

import config as C


class DebertaNLI:
    def __init__(self, model_name=None, max_premise_tokens=380, overlap_lines=2):
        self.remote = bool(C.NLI_BASE_URL)
        self.max_premise_tokens, self.overlap = max_premise_tokens, overlap_lines
        self._cache: Dict[str, List[str]] = {}
        self.stub = (model_name or C.NLI_MODEL) == "stub"
        if self.stub:  # offline smoke tests only
            self.size = lambda line: len(line.split())
            return
        if self.remote:
            import requests
            self.s = requests.Session()
            self.url = C.NLI_BASE_URL.rstrip("/") + "/nli"
            self.headers = {"X-API-Key": C.NLI_API_KEY} if C.NLI_API_KEY else {}
            self.size = lambda line: len(line.split()) * 1.3
            return
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        self.torch = torch
        name = model_name or C.NLI_MODEL
        self.dev = "cuda" if torch.cuda.is_available() else "cpu"
        self.tok = AutoTokenizer.from_pretrained(name)
        self.model = AutoModelForSequenceClassification.from_pretrained(name).to(self.dev).eval()
        lab = {v.lower(): k for k, v in self.model.config.id2label.items()}
        self.ie = next(v for k, v in lab.items() if "entail" in k)
        self.ic = next(v for k, v in lab.items() if "contra" in k)
        self.inn = next(v for k, v in lab.items() if "neut" in k)
        self.size = lambda line: len(self.tok.tokenize(line))

    def chunk(self, premise: str) -> List[str]:
        if premise in self._cache:
            return self._cache[premise]
        lines = [l for l in premise.splitlines() if l.strip()]
        sizes = [self.size(l) for l in lines]
        chunks, start = [], 0
        while start < len(lines):
            end, tot = start, 0
            while end < len(lines) and (tot + sizes[end] <= self.max_premise_tokens or end == start):
                tot += sizes[end]
                end += 1
            chunks.append("\n".join(lines[start:end]))
            if end >= len(lines):
                break
            start = max(end - self.overlap, start + 1)
        self._cache[premise] = chunks or [premise]
        return self._cache[premise]

    def _pairs(self, chunks, hyp):
        if self.stub:
            import re
            w = set(re.findall(r"[a-z]{4,}", hyp.lower()))
            out = []
            for c in chunks:
                ov = len(w & set(re.findall(r"[a-z]{4,}", c.lower()))) / max(1, len(w))
                out.append((ov ** 2, 1 - ov ** 2 - 0.02, 0.02))
            return out
        if self.remote:
            out = []
            for c in chunks:
                r = self.s.post(self.url, json={"premise": c, "hypothesis": hyp}, headers=self.headers, timeout=120)
                r.raise_for_status()
                sc = r.json()["scores"]
                out.append((sc["entailment"], sc["neutral"], sc["contradiction"]))
            return out
        torch = self.torch
        with torch.no_grad():
            enc = self.tok(chunks, [hyp] * len(chunks), truncation="only_first", max_length=512,
                           padding=True, return_tensors="pt").to(self.dev)
            p = torch.softmax(self.model(**enc).logits.float(), -1).cpu().tolist()
        return [(x[self.ie], x[self.inn], x[self.ic]) for x in p]

    def score(self, premise: str, hypothesis: str) -> Dict:
        """Max-pool over chunks; neutral is taken from the best-entailing chunk (as in the baseline)."""
        chunks = self.chunk(premise)
        sc = self._pairs(chunks, hypothesis)
        ie = max(range(len(sc)), key=lambda i: sc[i][0])
        ic = max(range(len(sc)), key=lambda i: sc[i][2])
        return {"entailment": sc[ie][0], "neutral": sc[ie][1], "contradiction": sc[ic][2],
                "best_chunk": ie}
