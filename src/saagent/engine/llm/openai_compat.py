"""Generic OpenAI-compatible chat backend (httpx, no openai dep).

Shared by the local vLLM adapter and the Bailian/DashScope adapter. Robust by
design: any HTTP/parse error returns None so the pipeline falls back gracefully.
JSON is recovered downstream by llm.base.extract_json (tolerates <think> blocks).
"""
from __future__ import annotations

import httpx

from .base import LLMClient


class OpenAICompatLLM(LLMClient):
    available = True

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        extra_body: dict | None = None,
        timeout: float = 180.0,
    ):
        if not base_url:
            raise ValueError("base_url is required")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.extra_body = extra_body or {}
        self._client = httpx.Client(timeout=timeout)

    def complete_text(self, system: str, prompt: str) -> str | None:
        try:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            body = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
            }
            body.update(self.extra_body)
            r = self._client.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
            r.raise_for_status()
            data = r.json()
            text = (data["choices"][0]["message"]["content"] or "").strip()
            return text or None
        except Exception:
            return None
