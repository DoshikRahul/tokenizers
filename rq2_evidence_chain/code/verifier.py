"""Label-probability verifier used by U2, U3, U4 and S1.

score(messages, labels) -> {"probs": {label: p}, "label": argmax, "seconds": t}

Backends
  hf     : transformers (+ peft adapter, optional 4-bit). P(label) = softmax over the summed log-probs of
           each full label string after the assistant prefix. Exact and threshold-sweepable.
  openai : chat completion with logprobs/top_logprobs when the server supports them, else parsed text.
  stub   : lexical-overlap heuristic for offline smoke tests only.
"""
import math
import re
import time
from typing import Dict, List, Sequence

import config as C


def _softmax(xs):
    m = max(xs)
    es = [math.exp(x - m) for x in xs]
    s = sum(es)
    return [e / s for e in es]


class HFVerifier:
    def __init__(self, base=None, adapter=None, load_4bit=None):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.torch = torch
        base = base or C.VERIFIER_BASE_MODEL
        adapter = C.VERIFIER_ADAPTER if adapter is None else adapter
        load_4bit = C.VERIFIER_4BIT if load_4bit is None else load_4bit
        self.tok = AutoTokenizer.from_pretrained(adapter or base)
        kw = {"device_map": "auto"}
        if load_4bit:
            from transformers import BitsAndBytesConfig
            # 1080 Ti (sm_61) has no bf16: compute in fp16
            kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                           bnb_4bit_compute_dtype=torch.float16,
                                                           bnb_4bit_use_double_quant=True)
        else:
            kw["torch_dtype"] = torch.float16
        model = AutoModelForCausalLM.from_pretrained(base, **kw)
        if adapter:
            from peft import PeftModel
            model = PeftModel.from_pretrained(model, adapter)
        self.model = model.eval()
        self.name = (adapter or base).rstrip("/").split("/")[-1]

    def n_tokens(self, text: str) -> int:
        return len(self.tok(text, add_special_tokens=False)["input_ids"])

    def score(self, messages, labels: Sequence[str]) -> Dict:
        torch = self.torch
        t0 = time.perf_counter()
        prompt = self.tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        p_ids = self.tok(prompt, add_special_tokens=False)["input_ids"]
        if len(p_ids) > C.VERIFIER_MAX_INPUT_TOKENS:  # keep the end (statement + 'Label:')
            p_ids = p_ids[:64] + p_ids[-(C.VERIFIER_MAX_INPUT_TOKENS - 64):]
        lab_ids = [self.tok(l, add_special_tokens=False)["input_ids"] for l in labels]
        dev = self.model.device
        scores = []
        with torch.no_grad():
            # One forward per label over prompt+label, keeping logits only for the label positions
            # (full-vocab logits for a 3k-token prompt would not fit on an 11 GB card).
            for ids in lab_ids:
                seq = torch.tensor([p_ids + ids], device=dev)
                keep = len(ids) + 1
                try:
                    logits = self.model(seq, logits_to_keep=keep).logits[0]
                except TypeError:  # older transformers
                    logits = self.model(seq, num_logits_to_keep=keep).logits[0]
                lps = torch.log_softmax(logits[:-1].float(), -1)  # position j predicts label token j
                scores.append(float(sum(lps[j, t] for j, t in enumerate(ids))))
        probs = dict(zip(labels, _softmax(scores)))
        return {"probs": probs, "label": max(probs, key=probs.get), "seconds": time.perf_counter() - t0}


class OpenAIVerifier:
    def __init__(self, base_url=None, model=None, api_key=None):
        import requests
        self.s = requests.Session()
        self.url = (base_url or C.VERIFIER_BASE_URL).rstrip("/") + "/chat/completions"
        self.model = model or C.VERIFIER_MODEL
        self.key = api_key if api_key is not None else C.VERIFIER_API_KEY
        self.name = self.model.split("/")[-1]
        self.logprobs_ok = True

    def n_tokens(self, text: str) -> int:
        return int(len(text.split()) * 1.4)

    def score(self, messages, labels):
        t0 = time.perf_counter()
        payload = {"model": self.model, "messages": messages, "temperature": 0.0, "max_tokens": 8}
        if self.logprobs_ok:
            payload.update(logprobs=True, top_logprobs=20)
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        body, last = None, "no attempt succeeded"
        for attempt in range(3):
            try:
                r = self.s.post(self.url, json=payload, headers=headers, timeout=120)
                if r.status_code in (400, 422) and self.logprobs_ok:  # server refuses logprobs fields
                    self.logprobs_ok = False
                    payload.pop("logprobs", None), payload.pop("top_logprobs", None)
                    continue
                r.raise_for_status()
                body = r.json()
                break
            except Exception as exc:
                last = exc
                time.sleep(2 * (attempt + 1))
        if body is None:
            raise RuntimeError(f"verifier call failed: {last}")
        ch = body["choices"][0]
        text = (ch["message"].get("content") or "").strip().lower()
        probs = None
        try:
            top = ch["logprobs"]["content"][0]["top_logprobs"]
            acc = {l: -1e9 for l in labels}
            for t in top:
                tok = t["token"].strip().lower()
                if not tok:
                    continue
                for l in labels:
                    if l.startswith(tok) or tok.startswith(l):
                        acc[l] = max(acc[l], t["logprob"])
            # labels sharing a first token (chain_ok / chain_broken) need the generated text to split them
            if len({l[:4] for l in labels}) < len(labels):
                raise KeyError
            if max(acc.values()) > -1e8:
                probs = dict(zip(labels, _softmax(list(acc.values()))))
        except (KeyError, TypeError, IndexError):
            probs = None
        if probs is None:
            hit = next((l for l in sorted(labels, key=len, reverse=True) if l in text), labels[-1])
            probs = {l: float(l == hit) for l in labels}
        return {"probs": probs, "label": max(probs, key=probs.get), "seconds": time.perf_counter() - t0,
                "raw": text}


class StubVerifier:
    """Offline heuristic. NOT a baseline; exists so the pipeline can be smoke-tested without GPUs."""
    name = "stub"

    def n_tokens(self, text):
        return len(text.split())

    def score(self, messages, labels):
        user = messages[-1]["content"]
        stmt = re.search(r"Statement:\s*(.*?)(?:\n|$)", user)
        stmt = stmt.group(1) if stmt else user[-200:]
        ev = user.replace(stmt, "")
        w = set(re.findall(r"[a-z]{4,}", stmt.lower())) - {"regarding", "patient", "will"}
        e = set(re.findall(r"[a-z]{4,}", ev.lower()))
        ov = len(w & e) / max(1, len(w))
        if labels == C.LABELS_ENTAIL:
            p = [ov ** 2, 0.05, 1 - ov ** 2]
        else:
            p = [min(0.95, ov + 0.2), max(0.05, 0.8 - ov)]
        s = sum(p)
        probs = {l: x / s for l, x in zip(labels, p)}
        return {"probs": probs, "label": max(probs, key=probs.get), "seconds": 0.0}


def make_verifier(backend=None):
    backend = backend or C.VERIFIER_BACKEND
    if backend == "hf":
        return HFVerifier()
    if backend == "openai":
        return OpenAIVerifier()
    if backend == "stub":
        return StubVerifier()
    raise ValueError(backend)
