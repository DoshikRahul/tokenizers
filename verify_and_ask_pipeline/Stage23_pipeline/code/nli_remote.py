"""Remote NLI scorer: same interface as nli_scorer.NLIScorer, but calls a DeBERTa NLI API
(POST /nli with an X-API-Key header, GET /health) hosted on a GPU machine.

The API takes one (premise, hypothesis) pair, so the dialogue is split into line-based chunks
(a word budget instead of a tokenizer) and entailment / contradiction are max-pooled over chunks,
exactly like the local scorer.
"""
from typing import Dict, List

import config as C


class RemoteNLIScorer:
    def __init__(self, base_url: str, api_key: str = "", max_words: int = 220,
                 overlap_lines: int = 2, timeout: int = 120):
        import requests
        self.url = base_url.rstrip("/")
        self.headers = {"X-API-Key": api_key} if api_key else {}
        self.max_words, self.overlap_lines, self.timeout = max_words, overlap_lines, timeout
        self.session = requests.Session()
        self._chunk_cache: Dict[str, List[str]] = {}
        health = self.session.get(self.url + "/health", timeout=15)
        health.raise_for_status()
        self.server_info = health.json()
        print(f"Remote NLI: {self.server_info}")
        # /health needs no key, so make one authenticated call now to fail fast on a bad key.
        probe = self.session.post(self.url + "/nli", headers=self.headers, timeout=self.timeout,
                                  json={"premise": "The sky is blue.", "hypothesis": "The sky is blue."})
        if probe.status_code in (401, 403):
            raise RuntimeError(f"NLI server rejected the API key (HTTP {probe.status_code}). "
                               "Set $env:NLI_API_KEY to the full key and try again.")
        probe.raise_for_status()

    def chunk(self, premise: str) -> List[str]:
        if premise in self._chunk_cache:
            return self._chunk_cache[premise]
        lines = [l for l in premise.splitlines() if l.strip()]
        sizes = [len(l.split()) for l in lines]
        chunks, start = [], 0
        while start < len(lines):
            end, total = start, 0
            while end < len(lines) and (total + sizes[end] <= self.max_words or end == start):
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
        import re
        lines = [l.strip() for l in chunk.splitlines() if len(l.split()) >= 3] or [chunk[:200]]
        hyp = set(re.findall(r"\w+", hypothesis.lower()))
        return max(lines, key=lambda l: len(hyp & set(re.findall(r"\w+", l.lower()))))

    def _one(self, premise: str, hypothesis: str) -> Dict:
        last = None
        for _ in range(3):
            try:
                r = self.session.post(self.url + "/nli", headers=self.headers, timeout=self.timeout,
                                      json={"premise": premise, "hypothesis": hypothesis})
                r.raise_for_status()
                return r.json()["scores"]
            except Exception as exc:
                last = exc
        raise RuntimeError(f"Remote NLI call failed: {last}")

    def score(self, premise: str, hypothesis: str) -> Dict:
        chunks = self.chunk(premise)
        scores = [self._one(c, hypothesis) for c in chunks]
        e_idx = max(range(len(chunks)), key=lambda i: scores[i]["entailment"])
        c_idx = max(range(len(chunks)), key=lambda i: scores[i]["contradiction"])
        return {
            "entailment": float(scores[e_idx]["entailment"]),
            "neutral": float(scores[e_idx]["neutral"]),
            "contradiction": float(scores[c_idx]["contradiction"]),
            "support_evidence": self.best_line(chunks[e_idx], hypothesis),
            "contradiction_evidence": self.best_line(chunks[c_idx], hypothesis),
        }


def make_nli_scorer(local_model_name: str = None):
    """Remote API when NLI_BASE_URL is set, otherwise load the model on this machine."""
    if C.NLI_BACKEND == "remote":
        return RemoteNLIScorer(C.NLI_BASE_URL, C.NLI_API_KEY, max_words=C.NLI_MAX_WORDS)
    from nli_scorer import NLIScorer
    return NLIScorer(model_name=local_model_name or C.NLI_MODEL)
