"""Generator LLM client (planting errors, feature extraction, linking). Not the verifier.

Backends: "openai" (any /v1/chat/completions server: Qwen3-14B host.py, OpenRouter, vLLM, llama.cpp),
"ollama", and "stub" (offline smoke tests).
"""
import time

import config as C
from common import parse_json_loose


class GenLLM:
    def __init__(self, backend=None, base_url=None, model=None, api_key=None, retries=3):
        self.backend = backend or C.GEN_BACKEND
        self.base_url = (base_url or C.GEN_BASE_URL).rstrip("/")
        self.model = model or (C.GEN_MODEL if self.backend == "openai" else C.OLLAMA_MODEL)
        self.api_key = api_key if api_key is not None else C.GEN_API_KEY
        self.retries = retries
        self.stub_fn = None  # tests may inject: fn(system, user) -> str

    def chat(self, system, user, temperature=0.0, max_tokens=1500, json_format=False) -> str:
        if self.backend == "stub":
            if self.stub_fn is None:
                from tests.stub_llm import respond
                self.stub_fn = respond
            return self.stub_fn(system, user)
        import requests
        if C.GEN_NO_THINK and "qwen3" in self.model.lower():
            system = system + "\n/no_think"
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if self.backend == "openai":
            url = self.base_url + ("" if self.base_url.endswith("/chat/completions") else "/chat/completions")
            payload = {"model": self.model, "messages": msgs, "temperature": temperature, "max_tokens": max_tokens}
            if json_format and C.GEN_JSON_MODE:
                payload["response_format"] = {"type": "json_object"}
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        else:
            url = C.OLLAMA_BASE.rstrip("/") + "/api/chat"
            payload = {"model": self.model, "messages": msgs, "stream": False,
                       "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": 8192}}
            if json_format:
                payload["format"] = "json"
            headers = {}
        last = None
        for attempt in range(1, self.retries + 1):
            try:
                r = requests.post(url, json=payload, headers=headers, timeout=C.GEN_TIMEOUT)
                r.raise_for_status()
                body = r.json()
                text = (body["choices"][0]["message"].get("content") if self.backend == "openai"
                        else body.get("message", {}).get("content")) or ""
                if text.strip():
                    return text.strip()
                last = "empty response"
            except Exception as exc:
                last = f"{type(exc).__name__}: {exc}"
            time.sleep(2 * attempt)
        raise RuntimeError(f"Generator LLM failed after {self.retries} attempts: {last}")

    def chat_json(self, system, user, **kw):
        out = parse_json_loose(self.chat(system, user, json_format=True, **kw))
        if out is None:  # one repair attempt
            out = parse_json_loose(self.chat(system, user + "\n\nReturn ONLY valid JSON.", json_format=True, **kw))
        return out
