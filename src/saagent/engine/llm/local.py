"""Local OpenAI-compatible LLM backend (e.g. vLLM-served Qwen3-8B).

Thin wrapper over OpenAICompatLLM; for Qwen3 we disable thinking via vLLM's
chat_template_kwargs so the response is plain JSON instead of <think>...</think>.
"""
from __future__ import annotations

from ..config import Settings
from .openai_compat import OpenAICompatLLM


class LocalLLM(OpenAICompatLLM):
    def __init__(self, settings: Settings):
        if not settings.local_base_url:
            raise ValueError("local_base_url not set")
        super().__init__(
            base_url=settings.local_base_url,
            model=settings.local_model,
            max_tokens=settings.llm_max_tokens,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
