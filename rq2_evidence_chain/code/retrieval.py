"""Hybrid retrieval: BM25 + dense embeddings fused with Reciprocal Rank Fusion (Cormack et al., 2009).

Used for (a) dialogue turns (S2: top-k turns vs whole dialogue) and (b) MedlinePlus passages (U4).
"""
import re
from typing import Dict, List

import config as C

_TOK = re.compile(r"[a-z0-9]+")
_STOP = set("the a an and or of to in on for with is are was were be been has have had he she they his her "
            "their it this that at by as from patient doctor will we i you your my me".split())


def tokenize(text: str) -> List[str]:
    return [t for t in _TOK.findall(text.lower()) if t not in _STOP]


_EMBEDDERS = {}


def get_embedder(name=None):
    name = name or C.EMBED_MODEL
    if name not in _EMBEDDERS:
        if name == "stub":
            _EMBEDDERS[name] = _StubEmbedder()
        else:
            from sentence_transformers import SentenceTransformer
            _EMBEDDERS[name] = SentenceTransformer(name)
    return _EMBEDDERS[name]


class _StubEmbedder:
    """Hashing bag-of-words embedder (offline tests)."""

    def encode(self, texts, normalize_embeddings=True, **kw):
        import numpy as np
        out = np.zeros((len(texts), 512), dtype="float32")
        for i, t in enumerate(texts):
            for w in tokenize(t):
                out[i, hash(w) % 512] += 1
        n = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.maximum(n, 1e-9)


class HybridIndex:
    def __init__(self, docs: List[Dict], text_key="text", embedder=None, embeddings=None):
        from rank_bm25 import BM25Okapi
        import numpy as np
        self.docs, self.text_key = docs, text_key
        texts = [d[text_key] for d in docs]
        self.bm25 = BM25Okapi([tokenize(t) or ["_"] for t in texts])
        self.emb = embedder or get_embedder()
        self.E = embeddings if embeddings is not None else \
            np.asarray(self.emb.encode(texts, normalize_embeddings=True, batch_size=64, show_progress_bar=False))

    def search(self, query: str, k: int = 5, rrf_k: int = None, pool: int = 50) -> List[Dict]:
        import numpy as np
        rrf_k = rrf_k or C.RRF_K
        n = len(self.docs)
        if n == 0:
            return []
        bm = self.bm25.get_scores(tokenize(query) or ["_"])
        q = np.asarray(self.emb.encode([query], normalize_embeddings=True))[0]
        cos = self.E @ q
        rank_bm = np.argsort(-bm)[:pool]
        rank_de = np.argsort(-cos)[:pool]
        fused: Dict[int, float] = {}
        for ranks in (rank_bm, rank_de):
            for r, i in enumerate(ranks):
                fused[int(i)] = fused.get(int(i), 0.0) + 1.0 / (rrf_k + r + 1)
        top = sorted(fused, key=fused.get, reverse=True)[:k]
        return [dict(self.docs[i], rrf=fused[i], cos=float(cos[i]), bm25=float(bm[i]), rank=j + 1)
                for j, i in enumerate(top)]


def turn_index(turns: List[Dict], embedder=None) -> HybridIndex:
    docs = [dict(t, text=f"{t['speaker']}: {t['text']}") for t in turns]
    return HybridIndex(docs, embedder=embedder)
