"""GPT-2 perplexity placement of a validated sentence inside a section.

Placement only: perplexity measures fluency, it does NOT show that the sentence is true.
Truth is established earlier by NLI validation against the conversation (omission.py).
Adapted from the uMedSum baseline (Algorithm 2) to operate on bullet lines.
"""
import math
from typing import List, Tuple

from config import PPL_MODEL


class PerplexityPlacer:
    def __init__(self, model_name: str = PPL_MODEL, device: str = None):
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM
        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForCausalLM.from_pretrained(model_name).to(self.device).eval()

    def perplexity(self, text: str) -> float:
        enc = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=1024).to(self.device)
        if enc.input_ids.shape[1] <= 1:
            return float("inf")
        with self.torch.no_grad():
            loss = self.model(enc.input_ids, labels=enc.input_ids).loss
        return math.exp(loss.item())

    def best_position(self, lines: List[str], new_line: str) -> Tuple[int, float]:
        """Index in `lines` (0..len) at which inserting `new_line` gives the lowest perplexity."""
        if not lines:
            return 0, float("nan")
        best_loc, best = len(lines), float("inf")
        for loc in range(len(lines) + 1):
            cand = lines[:loc] + [new_line] + lines[loc:]
            ppl = self.perplexity("\n".join(cand))
            if ppl < best:
                best_loc, best = loc, ppl
        return best_loc, best


class AppendPlacer:
    """Fallback when GPT-2 is unavailable: append at the end."""
    def best_position(self, lines: List[str], new_line: str) -> Tuple[int, float]:
        return len(lines), float("nan")
