"""Memory-bounded generation for the project's Qwen3-14B Engine (host.py stays unmodified).

Why: on 4x RTX 2080 Ti (10.57 GiB usable each) the FP16 weights already take
~6-8 GiB per GPU. host.Engine.complete() prefills the whole prompt in a single
forward pass, so late-consultation prompts (5-7k tokens) need several GiB of
temporary activations at once -> CUDA OOM, and the client retries the same
prompt into the same OOM.

Fix: chunked prefill. The prompt is pushed through the model PREFILL_CHUNK_TOKENS
at a time into a KV cache, then generate() continues from that cache. Output is
the same; peak activation memory no longer grows with prompt length. If an OOM
still happens, the cache is released and the request is retried once with
smaller chunks before reporting 503.
"""
from __future__ import annotations

import gc
import json
import logging
import os
import time
import uuid

from fastapi import HTTPException

import host as qwen_host

LOG = logging.getLogger("tokenizers_ui.qwen_engine")


def release_cuda_memory():
    import torch

    gc.collect()
    for index in range(torch.cuda.device_count()):
        with torch.cuda.device(index):
            torch.cuda.empty_cache()


class ChunkedPrefillEngine(qwen_host.Engine):
    chunk_tokens = int(os.getenv("PREFILL_CHUNK_TOKENS", "512"))
    fallback_chunk_tokens = int(os.getenv("PREFILL_FALLBACK_CHUNK_TOKENS", "128"))

    def _generate(self, input_ids, request, chunk: int):
        import torch
        from transformers import DynamicCache

        sample = request.temperature > 0
        total = input_ids.shape[-1]
        cache = DynamicCache()
        with torch.inference_mode():
            # Prefill everything except the last prompt token in bounded chunks.
            for start in range(0, total - 1, chunk):
                end = min(start + chunk, total - 1)
                self.model(input_ids=input_ids[:, start:end], past_key_values=cache, use_cache=True,
                           cache_position=torch.arange(start, end, device=input_ids.device),
                           logits_to_keep=1)
            # generate() sees the cached prefix and only runs the remaining token(s).
            outputs = self.model.generate(
                input_ids=input_ids, attention_mask=torch.ones_like(input_ids), past_key_values=cache,
                max_new_tokens=request.max_tokens, do_sample=sample,
                temperature=request.temperature if sample else None,
                top_p=request.top_p if sample else None, top_k=20 if sample else None,
                repetition_penalty=1.0,
                pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id,
                use_cache=True,
            )
        generated = outputs[0, total:].tolist()
        del outputs, cache
        return generated

    def complete(self, request: "qwen_host.ChatRequest") -> dict:
        """Same contract and checks as host.Engine.complete, with chunked prefill."""
        import torch
        from transformers import set_seed

        messages = [message.model_dump() for message in request.messages]
        json_mode = request.response_format is not None and request.response_format.type == "json_object"
        if json_mode:
            instruction = "Return exactly one valid JSON object. Do not use Markdown fences or text outside the object."
            if messages[0]["role"] == "system":
                messages[0]["content"] += "\n\n" + instruction
            else:
                messages.insert(0, {"role": "system", "content": instruction})
        text = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                                  enable_thinking=False)
        inputs = self.tokenizer(text, return_tensors="pt", add_special_tokens=False)
        prompt_tokens = inputs["input_ids"].shape[-1]
        if prompt_tokens + request.max_tokens > self.settings.context_tokens:
            raise HTTPException(400, detail=(
                f"Prompt has {prompt_tokens} tokens; with max_tokens={request.max_tokens} "
                f"it exceeds the {self.settings.context_tokens}-token context limit. "
                "Shorten the history or reduce max_tokens. Nothing was silently truncated."))
        if request.seed is not None:
            set_seed(request.seed)
        input_ids = inputs["input_ids"].to(self.input_device)
        for index in range(torch.cuda.device_count()):
            torch.cuda.reset_peak_memory_stats(index)
        started = time.time()
        generated = None
        for chunk in (self.chunk_tokens, self.fallback_chunk_tokens):
            try:
                generated = self._generate(input_ids, request, chunk)
                break
            except torch.cuda.OutOfMemoryError:
                LOG.warning("CUDA OOM (prompt %s tokens, chunk %s); releasing cache and retrying smaller",
                            prompt_tokens, chunk)
                release_cuda_memory()
        if generated is None:
            raise torch.cuda.OutOfMemoryError(  # host.py's endpoint turns this into HTTP 503
                f"Out of GPU memory even with {self.fallback_chunk_tokens}-token prefill chunks.")
        LOG.info("generated %s tokens for a %s-token prompt in %.1fs (peak GPU alloc %s GiB)",
                 len(generated), prompt_tokens, time.time() - started,
                 [round(torch.cuda.max_memory_allocated(i) / 1024**3, 2) for i in range(torch.cuda.device_count())])
        content = self.tokenizer.decode(generated, skip_special_tokens=True).strip()
        if not content:
            raise HTTPException(502, "The model returned empty text. Retry the request.")
        if json_mode:
            try:
                parsed = json.loads(content)
                if not isinstance(parsed, dict):
                    raise ValueError("Expected an object.")
            except (json.JSONDecodeError, ValueError) as exc:
                raise HTTPException(502, "Model did not return a valid JSON object. Retry, simplify the prompt, or increase max_tokens.") from exc
        eos = self.model.generation_config.eos_token_id
        eos = {eos} if isinstance(eos, int) else set(eos or [])
        finish_reason = "stop" if generated and generated[-1] in eos else "length"
        return {
            "id": "chatcmpl-" + uuid.uuid4().hex, "object": "chat.completion", "created": int(time.time()),
            "model": self.settings.served_name,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                         "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": len(generated),
                      "total_tokens": prompt_tokens + len(generated)},
        }
