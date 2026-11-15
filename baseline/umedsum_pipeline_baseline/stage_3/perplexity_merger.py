"""
Perplexity-Guided Sentence Insertion for uMedSum Stage 3.
Implements Algorithm 2 from Nagar et al., ACL 2025 (Section 3.3 & Appendix A.3):
- Evaluates candidate insertion locations using GPT-2 perplexity.
- Selects the insertion position l* that minimizes total summary perplexity.
"""

import math
import torch
import pysbd
from typing import List, Tuple
from transformers import AutoTokenizer, AutoModelForCausalLM

DEFAULT_PPL_MODEL = "gpt2"

class PerplexityMerger:
    def __init__(self, model_name: str = DEFAULT_PPL_MODEL, device: str = None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        print(f"Loading fluency LM '{model_name}' on {self.device}...")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForCausalLM.from_pretrained(model_name).to(self.device)
        self.model.eval()
        self.segmenter = pysbd.Segmenter(language="en", clean=False)

    def split_sentences(self, text: str) -> List[str]:
        """Split text into sentences using PySBD."""
        units = self.segmenter.segment(text)
        return [u.strip() for u in units if len(u.strip().split()) >= 2]

    @torch.no_grad()
    def calculate_perplexity(self, text: str) -> float:
        """Calculate language model perplexity for a piece of text."""
        encodings = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=1024).to(self.device)
        input_ids = encodings.input_ids
        if input_ids.shape[1] <= 1:
            return float("inf")

        outputs = self.model(input_ids, labels=input_ids)
        neg_log_likelihood = outputs.loss
        ppl = math.exp(neg_log_likelihood.item())
        return ppl

    def insert_at_location(self, sentences: List[str], missing_sentence: str, loc: int) -> str:
        """Insert a missing sentence at index loc in the list of sentences."""
        new_sentences = list(sentences)
        new_sentences.insert(loc, missing_sentence)
        return " ".join(new_sentences)

    def merge_missing_sentences(
        self,
        stage2_summary: str,
        missing_sentences: List[str]
    ) -> Tuple[str, List[dict]]:
        """
        Greedily merges each missing sentence into the summary at the location of minimum perplexity.
        Implements Algorithm 2.
        """
        if not missing_sentences:
            return stage2_summary, []

        current_summary = stage2_summary.strip()
        insertion_log = []

        for missing_sent in missing_sentences:
            sentences = self.split_sentences(current_summary)

            # If current summary is empty, the missing sentence becomes the summary
            if not sentences:
                current_summary = missing_sent
                insertion_log.append({
                    "inserted_sentence": missing_sent,
                    "location_index": 0,
                    "best_ppl": None
                })
                continue

            best_loc = 0
            best_ppl = float("inf")

            # Candidate locations: 0 to len(sentences) inclusive
            for loc in range(len(sentences) + 1):
                candidate_text = self.insert_at_location(sentences, missing_sent, loc)
                ppl = self.calculate_perplexity(candidate_text)
                if ppl < best_ppl:
                    best_ppl = ppl
                    best_loc = loc

            # Insert at best location
            current_summary = self.insert_at_location(sentences, missing_sent, best_loc)
            insertion_log.append({
                "inserted_sentence": missing_sent,
                "location_index": best_loc,
                "best_ppl": round(best_ppl, 2)
            })

        return current_summary, insertion_log
