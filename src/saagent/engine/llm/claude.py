"""Claude (Anthropic) LLM backend."""
from __future__ import annotations

import sys
import time

from ..config import Settings
from .base import LLMClient

_DEFAULT_MODEL = "claude-sonnet-4-6"
_THROTTLE_MARKERS = ("限流", "Throttling", "quota exceeded", "MPE-429", "Rate limit", "rate limit")
_MAX_RETRIES = 3


class ClaudeLLM(LLMClient):
    available = True

    def __init__(self, settings: Settings):
        import anthropic  # imported lazily so the dep stays optional

        kwargs: dict = {}
        if settings.anthropic_api_key:
            kwargs["api_key"] = settings.anthropic_api_key
        if settings.anthropic_auth_token:
            kwargs["auth_token"] = settings.anthropic_auth_token
        if settings.anthropic_base_url:
            kwargs["base_url"] = settings.anthropic_base_url
        self._client = anthropic.Anthropic(**kwargs)
        self.model = settings.llm_model or _DEFAULT_MODEL
        self.max_tokens = settings.llm_max_tokens

    def _is_throttle(self, exc: Exception) -> bool:
        msg = str(getattr(exc, "message", "")) + str(getattr(exc, "body", ""))
        return any(m in msg for m in _THROTTLE_MARKERS)

    def complete_text(self, system: str, prompt: str) -> str | None:
        for attempt in range(_MAX_RETRIES):
            try:
                resp = self._client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": prompt}],
                )
                parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
                return "\n".join(parts).strip() or None
            except Exception as e:
                if self._is_throttle(e) and attempt < _MAX_RETRIES - 1:
                    wait = 2 ** (attempt + 1)
                    print(f"  [engine-llm] throttled, retrying in {wait}s… ({e})", file=sys.stderr)
                    time.sleep(wait)
                    continue
                print(f"  [engine-llm] complete_text failed: {type(e).__name__}: {e}", file=sys.stderr)
                return None
        return None
