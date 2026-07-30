"""OpenAI-compatible Stirrup client (for DashScope / vLLM / any /v1 chat endpoint).

Stirrup ships ChatCompletionsClient, but it conflates the context window and the
per-request output cap into one ``max_tokens`` and emits ``max_completion_tokens``
(which DashScope's compatible mode does not accept). This thin client separates the
two and uses the plain ``max_tokens`` request param, while reusing Stirrup's own
message/tool converters so tool calling stays identical to the built-in client.
"""

from __future__ import annotations

from time import perf_counter
from typing import Any

from openai import AsyncOpenAI, APIConnectionError, APITimeoutError, InternalServerError, RateLimitError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from stirrup.clients.utils import to_openai_messages, to_openai_tools
from stirrup.core.exceptions import ContextOverflowError
from stirrup.core.models import AssistantMessage, ChatMessage, Reasoning, TokenUsage, Tool, ToolCall

__all__ = ["OpenAICompatClient"]


class OpenAICompatClient:
    """Stirrup LLMClient over any OpenAI-compatible chat/completions endpoint."""

    def __init__(
        self,
        model: str,
        *,
        base_url: str,
        api_key: str,
        context_window: int = 128_000,
        max_output_tokens: int = 8192,
        temperature: float | None = None,
        timeout: float | None = 300.0,
        max_retries: int = 2,
        kwargs: dict[str, Any] | None = None,
    ) -> None:
        self._model = model
        self._context_window = context_window
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._kwargs = kwargs or {}
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=max_retries)

    @property
    def max_tokens(self) -> int:
        return self._context_window

    @property
    def model_slug(self) -> str:
        return self._model

    @retry(
        retry=retry_if_exception_type((APIConnectionError, APITimeoutError, RateLimitError, InternalServerError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=2, max=30),
    )
    async def generate(self, messages: list[ChatMessage], tools: dict[str, Tool]) -> AssistantMessage:
        req: dict[str, Any] = {
            "model": self._model,
            "messages": to_openai_messages(messages),
            "max_tokens": self._max_output_tokens,
            **self._kwargs,
        }
        if tools:
            req["tools"] = to_openai_tools(tools)
            req["tool_choice"] = "auto"
        if self._temperature is not None:
            req["temperature"] = self._temperature

        start = perf_counter()
        resp = await self._client.chat.completions.create(**req)
        end = perf_counter()

        choice = resp.choices[0]
        if choice.finish_reason in ("max_tokens", "length"):
            raise ContextOverflowError(
                f"max output tokens reached for {self._model} (finish_reason={choice.finish_reason})."
            )
        msg = choice.message

        reasoning: Reasoning | None = None
        rc = getattr(msg, "reasoning_content", None)
        if rc:
            reasoning = Reasoning(content=rc)

        tool_calls = [
            ToolCall(tool_call_id=tc.id, name=tc.function.name, arguments=tc.function.arguments or "")
            for tc in (msg.tool_calls or [])
        ]

        usage = resp.usage
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0
        reasoning_tokens = 0
        details = getattr(usage, "completion_tokens_details", None)
        if details is not None:
            reasoning_tokens = getattr(details, "reasoning_tokens", 0) or 0

        return AssistantMessage(
            reasoning=reasoning,
            content=msg.content or "",
            tool_calls=tool_calls,
            token_usage=TokenUsage(input=input_tokens, answer=output_tokens - reasoning_tokens, reasoning=reasoning_tokens),
            request_start_time=start,
            request_end_time=end,
        )
