"""
Lightweight Ollama client for local LLM inference in uMedSum Stage 1.
Communicates directly with Ollama's REST API using Python standard library (no pip packages needed).
"""

import json
import sys
import urllib.request
import urllib.error
from typing import Dict, Any, Optional

DEFAULT_OLLAMA_URL = "http://localhost:11434"

class OllamaClient:
    def __init__(self, base_url: str = DEFAULT_OLLAMA_URL, model: str = "llama3:8b", timeout: int = 300):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def check_connection(self) -> bool:
        """Check if Ollama service is running and accessible."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status == 200
        except Exception:
            return False

    def list_models(self) -> list:
        """List all models currently installed in Ollama."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    return [m.get("name") for m in data.get("models", [])]
        except Exception:
            pass
        return []

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.0,
        num_ctx: int = 8192,
        max_tokens: int = 1024
    ) -> str:
        """
        Generate completion using Ollama /api/generate endpoint.
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_ctx": num_ctx,
                "num_predict": max_tokens,
            }
        }
        if system:
            payload["system"] = system

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("response", "").strip()
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"Failed to connect to Ollama at {self.base_url}. Is Ollama running? Error: {e}"
            )
        except Exception as e:
            raise RuntimeError(f"Ollama generation failed: {e}")
