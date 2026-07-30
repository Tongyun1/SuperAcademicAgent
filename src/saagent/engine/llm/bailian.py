"""Bailian / DashScope (Alibaba Cloud) LLM backend — OpenAI-compatible mode.

Default endpoint is DashScope's OpenAI-compatible base URL; the model defaults to
Qwen via DashScope. Fill the API key via env (DASHSCOPE_API_KEY
or SAAS_BAILIAN_API_KEY) and optionally override base_url / model.

DashScope compatible-mode docs:
  https://help.aliyun.com/zh/model-studio/developer-reference/compatibility-of-openai-with-dashscope
"""
from __future__ import annotations

from ..config import Settings
from .openai_compat import OpenAICompatLLM


class BailianLLM(OpenAICompatLLM):
    def __init__(self, settings: Settings):
        if not settings.bailian_api_key:
            raise ValueError("bailian_api_key not set (DASHSCOPE_API_KEY / SAAS_BAILIAN_API_KEY)")
        extra: dict = {}
        # For Qwen3 thinking models on DashScope, thinking can be toggled with a
        # top-level `enable_thinking`. Only send it when explicitly configured, so
        # non-thinking models don't reject an unknown field.
        if settings.bailian_enable_thinking is not None:
            extra["enable_thinking"] = settings.bailian_enable_thinking
        super().__init__(
            base_url=settings.bailian_base_url,
            model=settings.bailian_model,
            api_key=settings.bailian_api_key,
            max_tokens=settings.llm_max_tokens,
            extra_body=extra,
        )
