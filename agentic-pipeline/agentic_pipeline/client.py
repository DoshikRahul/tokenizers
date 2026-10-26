"""JSON-prompted chat requests compatible with the project's hosted Qwen server."""
import asyncio
import json
import re
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class ModelError(RuntimeError):
    pass


class ModelClient:
    def __init__(self, base_url: str, model: str, api_key: str, *, timeout: float = 900, retries: int = 3,
                 transport=None, concurrency: int = 1):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.retries = retries
        self.output_limit = 2048
        self.semaphore = asyncio.Semaphore(concurrency)
        self.http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=5), trust_env=False, transport=transport,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )

    async def close(self):
        await self.http.aclose()

    async def check(self) -> dict:
        health_url = self.base_url.removesuffix("/v1") + "/health"
        try:
            health = await self.http.get(health_url, timeout=10)
            health.raise_for_status()
            info = health.json()
            if info.get("status") != "ready":
                raise ModelError("The model endpoint is not ready.")
            response = await self.http.get(self.base_url + "/models", timeout=10)
            response.raise_for_status()
            available = [entry["id"] for entry in response.json()["data"]]
            if self.model not in available:
                raise ModelError(f"Requested model {self.model!r}; endpoint serves {available}.")
            self.output_limit = int(info.get("max_output_tokens", 2048))
            return info
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise ModelError(f"Cannot reach/validate Qwen at {self.base_url}. Keep the model server and SSH tunnel running. {exc}") from exc

    async def complete(self, *, agent: str, phase: str, system: str, payload, output: type[T] | None,
                       max_tokens: int, temperature: float, log) -> T | str:
        if output is not None:
            system += "\n\nReturn exactly one JSON object matching this schema. Use its exact keys; no Markdown.\n" + json.dumps(output.model_json_schema(), ensure_ascii=False)
        user = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        current_payload = dict(payload) if isinstance(payload, dict) else payload
        token_budget = min(max_tokens, self.output_limit)
        repair = ""
        error = ""
        for attempt in range(1, self.retries + 1):
            request = {
                "model": self.model, "messages": messages + ([{"role": "user", "content": repair}] if repair else []),
                "max_tokens": token_budget, "temperature": temperature,
                "top_p": 0.8, "stream": False,
            }
            if output is not None:
                request["response_format"] = {"type": "json_object"}
            log.event({"event": "request", "agent": agent, "phase": phase, "attempt": attempt,
                       "model": self.model, "messages": request["messages"], "max_tokens": request["max_tokens"],
                       "parameters": {key: value for key, value in request.items() if key != "messages"}})
            try:
                async with self.semaphore:
                    response = await self.http.post(self.base_url + "/chat/completions", json=request)
                context_error = re.search(r"Prompt has (\d+) tokens;.*?(\d+)-token context limit", response.text) if response.status_code == 400 else None
                if context_error:
                    error = f"Context limit: {response.text[:1500]}"
                    # Preserve the source transcript and evidence. Only redundant older
                    # conversation context or the requested output budget may be reduced.
                    trimmed = False
                    if isinstance(current_payload, dict):
                        for key in ("simulated_consultation", "recent_consultation", "recent_patient_responses"):
                            history = current_payload.get(key)
                            if isinstance(history, list) and len(history) > 2:
                                current_payload[key] = history[-2:]
                                messages[1]["content"] = json.dumps(current_payload, ensure_ascii=False)
                                log.event({"event": "context_adjustment", "agent": agent, "phase": phase,
                                           "action": "reduce_recent_history", "kept_messages": 2})
                                trimmed = True
                                break
                    if trimmed:
                        repair = ""
                        continue
                    available = int(context_error[2]) - int(context_error[1]) - 16
                    if 256 <= available < token_budget:
                        token_budget = available
                        repair = ""
                        log.event({"event": "context_adjustment", "agent": agent, "phase": phase,
                                   "action": "reduce_output_budget", "max_tokens": token_budget})
                        continue
                if response.status_code in {400, 401, 403, 404, 422}:
                    raise ModelError(f"Endpoint rejected {agent}: HTTP {response.status_code}: {response.text[:1500]}")
                response.raise_for_status()
                body = response.json()
                choice = body["choices"][0]
                text = choice["message"]["content"]
                log.event({"event": "response", "agent": agent, "phase": phase, "attempt": attempt,
                           "content": text, "finish_reason": choice.get("finish_reason"), "usage": body.get("usage")})
                if choice.get("finish_reason") == "length":
                    raise ValueError("Response reached its token limit. Give a shorter, complete answer.")
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("Response must contain nonempty text.")
                if output is None:
                    return text.strip()
                value = json.loads(text)
                parsed = output.model_validate(value)
                log.event({"event": "validated", "agent": agent, "phase": phase, "output": parsed.model_dump()})
                return parsed
            except httpx.ConnectError as exc:
                raise ModelError(f"Qwen connection failed at {self.base_url}; check the SSH tunnel.") from exc
            except (httpx.HTTPError, ValidationError, ValueError, KeyError, TypeError, IndexError) as exc:
                error = str(exc)
                log.event({"event": "retry", "agent": agent, "phase": phase, "attempt": attempt, "error": error[:2000]})
                repair = "The previous attempt failed validation: " + error[:1800] + ". Regenerate a concise complete response using the supplied information and exact schema."
                if attempt < self.retries:
                    await asyncio.sleep(min(attempt, 2))
        raise ModelError(f"{agent} failed after {self.retries} attempts: {error}")
