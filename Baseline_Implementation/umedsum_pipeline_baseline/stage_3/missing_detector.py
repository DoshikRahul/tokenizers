"""
Missing Information Detector for uMedSum Stage 3.
Implements the Missing Key Information Detection algorithm (Nagar et al., ACL 2025, Section 3.3):
- Computes embedding similarity between document key sentences and summary key phrases.
- Coverage score: covi_score = max_j { sim(kidoc, kjsumm) }
- Threshold: covmin = 0.4 (Paper Appendix A.7, Eq. 7)

Enhanced with exact dialogue citations and clinical action reasons.
"""

import numpy as np
from typing import List, Dict, Any
from sentence_transformers import SentenceTransformer

DEFAULT_COV_MIN = 0.4  # Paper Appendix A.7, Eq. 7

class MissingInformationDetector:
    def __init__(self, embedder: SentenceTransformer, cov_min: float = DEFAULT_COV_MIN):
        self.embedder = embedder
        self.cov_min = cov_min

    def detect_missing_sentences(
        self,
        key_sentences: List[str],
        summary_key_phrases: List[str]
    ) -> Dict[str, Any]:
        """
        Calculates coverage scores and identifies missing key information with citations.
        """
        if not key_sentences:
            return {
                "missing_sentences": [],
                "covered_sentences": [],
                "coverage_scores": []
            }

        # If summary has no key phrases at all, all key sentences are missing
        if not summary_key_phrases:
            return {
                "missing_sentences": key_sentences,
                "covered_sentences": [],
                "coverage_scores": [{
                    "sentence": s,
                    "citation_source": "src (dialogue key sentence)",
                    "citation_text": s,
                    "score": 0.0,
                    "action": "Added: entire summary lacked key phrases."
                } for s in key_sentences]
            }

        # Encode key sentences (m x d) and key phrases (n x d)
        doc_embs = self.embedder.encode(key_sentences, convert_to_numpy=True, normalize_embeddings=True)
        summ_embs = self.embedder.encode(summary_key_phrases, convert_to_numpy=True, normalize_embeddings=True)

        # Similarity matrix (m x n)
        sim_matrix = np.dot(doc_embs, summ_embs.T)

        missing_sentences = []
        covered_sentences = []
        coverage_scores = []

        for idx, sentence in enumerate(key_sentences):
            cov_score = float(np.max(sim_matrix[idx]))
            is_missing = cov_score <= self.cov_min

            score_info = {
                "sentence": sentence,
                "citation_source": "src (dialogue key sentence)",
                "citation_text": sentence,
                "score": round(cov_score, 4),
                "is_missing": is_missing,
                "action": (
                    "Added: Missing clinical dialogue detail (coverage < 0.40); inserted via GPT-2 fluency optimization."
                    if is_missing else
                    "Preserved: Dialogue detail already adequately covered in note (coverage >= 0.40)."
                )
            }
            coverage_scores.append(score_info)

            if is_missing:
                missing_sentences.append(sentence)
            else:
                covered_sentences.append(sentence)

        return {
            "missing_sentences": missing_sentences,
            "covered_sentences": covered_sentences,
            "coverage_scores": coverage_scores
        }
