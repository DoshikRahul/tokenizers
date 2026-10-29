"""
Key Information Extractor for uMedSum Stage 3.
Implements Algorithm 1 from Nagar et al., ACL 2025 (Section 3.3 & Appendix A.2):
- Source Document: Extracts top-M key sentences using MMR + Sentence-BERT (all-MiniLM-L6-v2).
- Stage 2 Summary: Extracts top-N key phrases (n-grams) using KeyBERT.
"""

import numpy as np
import pysbd
from typing import List, Tuple
from sentence_transformers import SentenceTransformer
from keybert import KeyBERT

DEFAULT_EMBEDDER_MODEL = "all-MiniLM-L6-v2"
DEFAULT_TOP_M = 2  # Paper Appendix A.7, Eq. 6

class KeyExtractor:
    def __init__(self, model_name: str = DEFAULT_EMBEDDER_MODEL, device: str = None):
        self.embedder = SentenceTransformer(model_name, device=device)
        self.keybert = KeyBERT(model=self.embedder)
        self.segmenter = pysbd.Segmenter(language="en", clean=False)

    def split_sentences(self, text: str) -> List[str]:
        """Split text into sentences using PySBD."""
        units = self.segmenter.segment(text)
        return [u.strip() for u in units if len(u.strip().split()) >= 3]

    def extract_document_key_sentences(
        self,
        document: str,
        top_m: int = DEFAULT_TOP_M,
        diversity: float = 0.5
    ) -> List[str]:
        """
        Extract top-M key sentences from the document using Maximal Marginal Relevance (MMR).
        Implements Algorithm 1 (lines 3-11 for document).
        """
        sentences = self.split_sentences(document)
        if not sentences or len(sentences) <= top_m:
            return sentences

        doc_embedding = self.embedder.encode(document, convert_to_numpy=True, normalize_embeddings=True)
        sent_embeddings = self.embedder.encode(sentences, convert_to_numpy=True, normalize_embeddings=True)

        # Relevance to document
        doc_sims = np.dot(sent_embeddings, doc_embedding)

        selected_indices = []
        candidate_indices = list(range(len(sentences)))

        while len(selected_indices) < top_m and candidate_indices:
            if not selected_indices:
                best_idx = candidate_indices[np.argmax(doc_sims[candidate_indices])]
            else:
                selected_embs = sent_embeddings[selected_indices]
                # Redundancy: max similarity to already selected sentences
                redundancy = np.max(np.dot(sent_embeddings[candidate_indices], selected_embs.T), axis=1)
                mmr_scores = diversity * doc_sims[candidate_indices] - (1 - diversity) * redundancy
                best_idx = candidate_indices[np.argmax(mmr_scores)]

            selected_indices.append(best_idx)
            candidate_indices.remove(best_idx)

        return [sentences[i] for i in selected_indices]

    def extract_summary_key_phrases(
        self,
        summary: str,
        top_n: int = 10,
        keyphrase_ngram_range: Tuple[int, int] = (1, 3)
    ) -> List[str]:
        """
        Extract key phrases (n-grams) from the Stage 2 summary using KeyBERT + MMR.
        """
        if not summary.strip():
            return []

        try:
            keywords = self.keybert.extract_keywords(
                summary,
                keyphrase_ngram_range=keyphrase_ngram_range,
                stop_words="english",
                use_mmr=True,
                diversity=0.4,
                top_n=top_n
            )
            return [kw[0] for kw in keywords]
        except Exception:
            # Fallback to simple tokenization if text is too short for keybert
            words = [w.strip() for w in summary.split() if len(w.strip()) > 3]
            return list(set(words))[:top_n]
