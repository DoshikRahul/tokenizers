"""
Optimized Batched NLI Scorer for uMedSum Stage 2 (Confabulation Removal).
Uses DeBERTa-v3-large with batched parallel inference across dialogue chunks for CPU/GPU acceleration.
Extracts supporting dialogue citations for every verified clinical unit.
"""

import re
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from typing import Dict, List, Any

DEFAULT_NLI_MODEL = "MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli"

class DebertaNLIScorer:
    def __init__(self, model_name: str = DEFAULT_NLI_MODEL, device: str = None, max_premise_tokens: int = 420):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        print(f"Loading NLI model '{model_name}' on {self.device}...")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name).to(self.device)
        self.model.eval()
        self.max_premise_tokens = max_premise_tokens

        # Label index mapping
        self.id2label = {idx: label.lower() for idx, label in self.model.config.id2label.items()}
        self.entail_idx = 0
        self.neutral_idx = 1
        self.contra_idx = 2

        for idx, label in self.id2label.items():
            if "entail" in label:
                self.entail_idx = idx
            elif "contra" in label:
                self.contra_idx = idx
            elif "neut" in label:
                self.neutral_idx = idx

        print(f"NLI model loaded successfully! [Entailment: {self.entail_idx}, Neutral: {self.neutral_idx}, Contradiction: {self.contra_idx}]")

    def chunk_dialogue(self, dialogue: str, stride: int = 320) -> List[str]:
        """Split dialogue into overlapping chunks with optimal stride."""
        tokens = self.tokenizer.tokenize(dialogue)
        if len(tokens) <= self.max_premise_tokens:
            return [dialogue]

        chunks = []
        for i in range(0, len(tokens), stride):
            chunk_tokens = tokens[i : i + self.max_premise_tokens]
            chunk_text = self.tokenizer.convert_tokens_to_string(chunk_tokens)
            chunks.append(chunk_text)
            if i + self.max_premise_tokens >= len(tokens):
                break
        return chunks if chunks else [dialogue]

    @staticmethod
    def extract_relevant_snippet(chunk: str, hypothesis: str) -> str:
        """Finds the most lexically relevant line/utterance within the best chunk for citation."""
        lines = [line.strip() for line in chunk.splitlines() if len(line.strip().split()) >= 3]
        if not lines:
            return chunk[:200]

        hyp_words = set(re.findall(r"\w+", hypothesis.lower()))
        best_line = lines[0]
        max_overlap = -1

        for line in lines:
            line_words = set(re.findall(r"\w+", line.lower()))
            overlap = len(hyp_words & line_words)
            if overlap > max_overlap:
                max_overlap = overlap
                best_line = line

        return best_line

    @torch.no_grad()
    def score_hypothesis(self, full_dialogue: str, hypothesis: str) -> Dict[str, Any]:
        """
        Batched evaluation: scores hypothesis against ALL dialogue chunks in a SINGLE forward pass.
        Returns entailment, neutral, contradiction, and the best supporting dialogue citation.
        """
        chunks = self.chunk_dialogue(full_dialogue)
        batch_hypotheses = [hypothesis] * len(chunks)

        inputs = self.tokenizer(
            chunks,
            batch_hypotheses,
            truncation=True,
            max_length=512,
            padding=True,
            return_tensors="pt"
        ).to(self.device)

        logits = self.model(**inputs).logits
        probs = torch.softmax(logits, dim=-1)  # shape: [num_chunks, 3]

        # Select chunk that gives the highest entailment score (max-pooling)
        entail_scores = probs[:, self.entail_idx]
        best_chunk_idx = torch.argmax(entail_scores).item()
        best_prob_vector = probs[best_chunk_idx].tolist()
        best_chunk_text = chunks[best_chunk_idx]

        citation = self.extract_relevant_snippet(best_chunk_text, hypothesis)

        return {
            "entailment": float(best_prob_vector[self.entail_idx]),
            "neutral": float(best_prob_vector[self.neutral_idx]),
            "contradiction": float(best_prob_vector[self.contra_idx]),
            "best_chunk_idx": best_chunk_idx,
            "best_citation": citation
        }
