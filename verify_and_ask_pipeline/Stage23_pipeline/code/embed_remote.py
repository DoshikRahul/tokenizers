"""Remote sentence embedder (all-MiniLM-L6-v2 served through llama.cpp, OpenAI-style /v1/embeddings).

Drop-in for the one SentenceTransformer method the pipeline uses:
    embedder.encode(list_of_texts, convert_to_numpy=True, normalize_embeddings=True) -> (n, 384) array
"""
import numpy as np

import config as C


class RemoteEmbedder:
    def __init__(self, base_url: str, model: str = "all-MiniLM-L6-v2", batch_size: int = 32, timeout: int = 120):
        import requests
        self.url = base_url.rstrip("/") + "/v1/embeddings"
        self.model, self.batch_size, self.timeout = model, batch_size, timeout
        self.session = requests.Session()
        health = self.session.get(base_url.rstrip("/") + "/health", timeout=15)
        health.raise_for_status()
        print(f"Remote embedder: {base_url} {health.text.strip()[:80]}")

    def _embed_batch(self, texts):
        last = None
        for _ in range(3):
            try:
                r = self.session.post(self.url, json={"model": self.model, "input": texts}, timeout=self.timeout)
                r.raise_for_status()
                items = sorted(r.json()["data"], key=lambda it: it.get("index", 0))
                return [it["embedding"] for it in items]
            except Exception as exc:
                last = exc
        raise RuntimeError(f"Remote embedding call failed: {last}")

    def encode(self, texts, convert_to_numpy=True, normalize_embeddings=True, **_ignored):
        single = isinstance(texts, str)
        texts = [texts] if single else list(texts)
        vecs = []
        for i in range(0, len(texts), self.batch_size):
            vecs.extend(self._embed_batch(texts[i:i + self.batch_size]))
        arr = np.asarray(vecs, dtype=np.float32).reshape(len(texts), -1)
        if normalize_embeddings:
            norms = np.linalg.norm(arr, axis=1, keepdims=True)
            arr = arr / np.where(norms == 0, 1, norms)
        return arr[0] if single else arr


def make_embedder():
    """Remote API when EMBED_BASE_URL is set, otherwise load MiniLM on this machine."""
    if C.EMBED_BACKEND == "remote":
        return RemoteEmbedder(C.EMBED_BASE_URL)
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(C.EMBED_MODEL)
