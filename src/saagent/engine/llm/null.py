"""No-op LLM, enabling pure graph-algorithm mode with zero configuration."""
from __future__ import annotations

from .base import LLMClient


class NullLLM(LLMClient):
    available = False

    def complete_text(self, system: str, prompt: str) -> str | None:
        return None

    def complete_json(self, system: str, prompt: str):
        return None
