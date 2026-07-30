"""Native Anthropic Messages API client for Stirrup.

Stirrup's ``LLMClient`` is a Protocol — the only hard requirement is::

    async def generate(messages, tools) -> AssistantMessage
    property model_slug -> str
    property max_tokens -> int   # context window, used by Agent for summarization

We talk directly to the Anthropic Messages API (native tool_use), which compatible
gateways support (verified in spikes/m0_*.py). This gives the highest-fidelity tool
calling and reuses the existing ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN config.

Key format translations (Stirrup <-> Anthropic):
  - SystemMessage      -> top-level ``system`` param (not a message)
  - UserMessage        -> {role: user, content: [text/image blocks]}
  - AssistantMessage   -> {role: assistant, content: [text] + [tool_use blocks]}
  - ToolMessage        -> {role: user, content: [{type: tool_result, ...}]}
                          (consecutive tool results merged into one user message,
                           as Anthropic requires)
"""

from __future__ import annotations

import json
import os
from time import perf_counter
from typing import Any

import anthropic
from anthropic import AsyncAnthropic
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from stirrup.core.exceptions import ContextOverflowError
from stirrup.core.models import (
    AssistantMessage,
    ChatMessage,
    Content,
    EmptyParams,
    ImageContentBlock,
    Reasoning,
    SystemMessage,
    TokenUsage,
    Tool,
    ToolCall,
    ToolMessage,
    UserMessage,
)

__all__ = ["AnthropicMessagesClient"]

# gateway throttling markers — some gateways return provider throttling as a
# 400 BadRequestError (not 429), so retry_if_exception_type misses it. Detect by body.
_THROTTLE_MARKERS = ("限流", "Throttling", "quota exceeded", "MPE-429", "Rate limit", "rate limit")


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(
        exc,
        (
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
            anthropic.RateLimitError,
            anthropic.InternalServerError,
        ),
    ):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        msg = str(getattr(exc, "message", "")) + str(getattr(exc, "body", ""))
        return any(mark in msg for mark in _THROTTLE_MARKERS)
    return False


def _text_from_content(content: Content) -> str:
    """Flatten Stirrup Content to plain text (best-effort; used for system + fallbacks)."""
    if isinstance(content, str):
        return content
    parts = [b for b in content if isinstance(b, str)]
    return "\n".join(parts)


def _content_to_anthropic_blocks(content: Content) -> list[dict[str, Any]]:
    """Convert Stirrup Content to a list of Anthropic content blocks (text + image)."""
    blocks: list[dict[str, Any]] = []
    if isinstance(content, str):
        if content:
            blocks.append({"type": "text", "text": content})
        return blocks
    for b in content:
        if isinstance(b, str):
            if b:
                blocks.append({"type": "text", "text": b})
        elif isinstance(b, ImageContentBlock):
            # data URL -> anthropic base64 image block
            url = b.to_base64_url()  # "data:<mime>;base64,<data>"
            header, data = url.split(",", 1)
            media_type = header.split(";")[0].removeprefix("data:")
            blocks.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": data},
                }
            )
        # audio/video not supported by this client -> silently dropped
    return blocks


def to_anthropic_tools(tools: dict[str, Tool]) -> list[dict[str, Any]]:
    """Convert Stirrup Tools to Anthropic tool definitions."""
    out: list[dict[str, Any]] = []
    for t in tools.values():
        if t.parameters is not EmptyParams:
            schema = t.parameters.model_json_schema()
        else:
            schema = {"type": "object", "properties": {}}
        out.append({"name": t.name, "description": t.description, "input_schema": schema})
    return out


def to_anthropic_messages(msgs: list[ChatMessage]) -> tuple[str | None, list[dict[str, Any]]]:
    """Convert Stirrup ChatMessages to (system, anthropic_messages).

    Consecutive ToolMessages are merged into a single user message carrying multiple
    ``tool_result`` blocks, which Anthropic requires after an assistant ``tool_use`` turn.
    """
    system_parts: list[str] = []
    out: list[dict[str, Any]] = []

    def _flush_pending_tool_results(pending: list[dict[str, Any]]) -> None:
        if pending:
            out.append({"role": "user", "content": list(pending)})
            pending.clear()

    pending_tool_results: list[dict[str, Any]] = []

    for m in msgs:
        if isinstance(m, SystemMessage):
            _flush_pending_tool_results(pending_tool_results)
            txt = _text_from_content(m.content)
            if txt:
                system_parts.append(txt)
        elif isinstance(m, ToolMessage):
            # accumulate; merged into one user message
            pending_tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": m.tool_call_id,
                    "content": _content_to_anthropic_blocks(m.content) or [{"type": "text", "text": ""}],
                    "is_error": not m.success and not m.args_was_valid,
                }
            )
        elif isinstance(m, UserMessage):
            _flush_pending_tool_results(pending_tool_results)
            blocks = _content_to_anthropic_blocks(m.content) or [{"type": "text", "text": ""}]
            out.append({"role": "user", "content": blocks})
        elif isinstance(m, AssistantMessage):
            _flush_pending_tool_results(pending_tool_results)
            blocks = _content_to_anthropic_blocks(m.content)
            for tc in m.tool_calls:
                try:
                    tool_input = json.loads(tc.arguments) if tc.arguments else {}
                except json.JSONDecodeError:
                    tool_input = {}
                blocks.append(
                    {"type": "tool_use", "id": tc.tool_call_id, "name": tc.name, "input": tool_input}
                )
            if not blocks:
                blocks = [{"type": "text", "text": ""}]
            out.append({"role": "assistant", "content": blocks})
        else:
            raise NotImplementedError(f"Unsupported message type: {type(m)}")

    _flush_pending_tool_results(pending_tool_results)
    system = "\n\n".join(system_parts) if system_parts else None
    return system, out


class AnthropicMessagesClient:
    """Stirrup LLMClient backed by the Anthropic Messages API (gateway compatible).

    Args:
        model: model slug (e.g. "qwen3.7-max").
        context_window: token budget Stirrup uses to decide when to summarize history.
        max_output_tokens: cap on generated tokens per request (Anthropic ``max_tokens``).
        base_url / auth_token / api_key: gateway config; default to ANTHROPIC_* env vars.
        temperature / timeout / kwargs: passed through to messages.create.
    """

    def __init__(
        self,
        model: str,
        *,
        context_window: int = 128_000,
        max_output_tokens: int = 8192,
        base_url: str | None = None,
        auth_token: str | None = None,
        api_key: str | None = None,
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

        client_kwargs: dict[str, Any] = {"max_retries": max_retries}
        if timeout is not None:
            client_kwargs["timeout"] = timeout
        base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL")
        auth_token = auth_token or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if base_url:
            client_kwargs["base_url"] = base_url
        if auth_token:
            client_kwargs["auth_token"] = auth_token
        if api_key:
            client_kwargs["api_key"] = api_key
        self._client = AsyncAnthropic(**client_kwargs)

    @property
    def max_tokens(self) -> int:
        return self._context_window

    @property
    def model_slug(self) -> str:
        return self._model

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(6),
        wait=wait_exponential(multiplier=2, min=2, max=30),
    )
    async def generate(self, messages: list[ChatMessage], tools: dict[str, Tool]) -> AssistantMessage:
        system, anthropic_msgs = to_anthropic_messages(messages)

        req: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_output_tokens,
            "messages": anthropic_msgs,
            **self._kwargs,
        }
        if system:
            req["system"] = system
        if tools:
            req["tools"] = to_anthropic_tools(tools)
        if self._temperature is not None:
            req["temperature"] = self._temperature

        start = perf_counter()
        resp = await self._client.messages.create(**req)
        end = perf_counter()

        if resp.stop_reason == "max_tokens":
            raise ContextOverflowError(
                f"max_tokens reached for model {self._model} (stop_reason=max_tokens). "
                "Increase max_output_tokens or reduce context."
            )

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        reasoning: Reasoning | None = None
        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(block.text)
            elif btype == "tool_use":
                tool_calls.append(
                    ToolCall(
                        tool_call_id=block.id,
                        name=block.name,
                        arguments=json.dumps(block.input or {}),
                    )
                )
            elif btype == "thinking":
                reasoning = Reasoning(
                    content=getattr(block, "thinking", "") or "",
                    signature=getattr(block, "signature", None),
                )

        usage = resp.usage
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0

        return AssistantMessage(
            reasoning=reasoning,
            content="\n".join(text_parts),
            tool_calls=tool_calls,
            token_usage=TokenUsage(input=input_tokens, answer=output_tokens, reasoning=0),
            request_start_time=start,
            request_end_time=end,
        )
