"""LLM client (inference only) with two backends:
  - "openai": any OpenAI-compatible /v1/chat/completions server (key from LLM_API_KEY),
  - "ollama": local Ollama /api/chat.
"""
import json
import re
import time
from typing import Any, Optional

import config as C


class LLMClient:
    def __init__(self, retries: int = 3):
        self.backend = C.LLM_BACKEND
        self.timeout, self.retries = C.OLLAMA_TIMEOUT, retries
        if self.backend == "openai":
            if not C.LLM_BASE_URL:
                raise RuntimeError("LLM_BASE_URL is not set (e.g. http://HOST:8080/v1).")
            self.url, self.model = C.LLM_BASE_URL.rstrip("/") + "/chat/completions", C.LLM_MODEL
        else:
            self.url, self.model = C.OLLAMA_BASE.rstrip("/") + "/api/chat", C.OLLAMA_MODEL

    def chat(self, system: str, user: str, temperature: float = 0.0,
             num_predict: int = 600, json_format: bool = False) -> str:
        import requests
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        headers = {}
        if self.backend == "openai":
            payload = {"model": self.model, "messages": messages, "temperature": temperature,
                       "max_tokens": num_predict}
            if json_format and C.LLM_JSON_MODE:
                payload["response_format"] = {"type": "json_object"}
            if C.LLM_API_KEY:
                headers["Authorization"] = f"Bearer {C.LLM_API_KEY}"
        else:
            payload = {"model": self.model, "messages": messages, "stream": False, "keep_alive": "10m",
                       "options": {"temperature": temperature, "num_ctx": C.OLLAMA_NUM_CTX,
                                   "num_predict": num_predict}}
            if json_format:
                payload["format"] = "json"
        last = None
        for attempt in range(1, self.retries + 1):
            try:
                r = requests.post(self.url, json=payload, headers=headers, timeout=self.timeout)
                r.raise_for_status()
                body = r.json()
                text = (body["choices"][0]["message"].get("content") if self.backend == "openai"
                        else body.get("message", {}).get("content")) or ""
                if text.strip():
                    return text.strip()
                last = "empty response"
            except Exception as exc:  # network / timeout: retry, then raise
                last = f"{type(exc).__name__}: {exc}"
            time.sleep(attempt * 2)
        raise RuntimeError(f"LLM call failed after {self.retries} attempts: {last}")

    def chat_json(self, system: str, user: str, **kw) -> Optional[Any]:
        """Return parsed JSON (object or list) or None if the output cannot be parsed."""
        return parse_json_loose(self.chat(system, user, json_format=True, **kw))


def parse_json_loose(text: str) -> Optional[Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
    return None
