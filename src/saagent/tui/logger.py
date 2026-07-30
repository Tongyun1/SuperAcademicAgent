"""Bridges stirrup's AgentLoggerBase callbacks into the chat session's real-terminal history.

Every callback here runs on the SAME asyncio loop/thread as the running agent turn
(stirrup invokes the logger synchronously from within the coroutine driving the turn task),
so it's safe to call straight into console.print — no thread-hop needed here
(unlike ask_user_bridge.py, which genuinely runs off-loop).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rich.text import Text
from stirrup import AssistantMessage, ToolMessage, UserMessage
from stirrup.utils.logging import AgentLoggerBase

from ..engine.cli import console
from .render import (
    render_assistant_text,
    render_context_summarization_note,
    render_system_note,
    render_tool_call_line,
    render_tool_result_block,
)

# Stirrup warns when its default code-exec / web tools are absent — this agent
# deliberately doesn't use them (mirrors saagent.build._QuietAgentLogger's filter).
_NOISE = ("Missing default tool", "no code execution tool")

# When the model emits N text-only assistant messages in a row (no tool call at
# all), it's stuck repeating itself instead of ending the turn with a finish tool.
# Stirrup's loop only breaks on finish_params, so we raise from the logger to
# force the run() coroutine to exit; app.py's turn handler catches this cleanly.
_RUNAWAY_TEXT_ONLY_THRESHOLD = 2


class RunawayLoopError(RuntimeError):
    """Raised from the logger when the agent won't stop emitting text-only replies."""


class ChatAgentLogger(AgentLoggerBase):
    """AgentLoggerBase implementation that prints into the real terminal scrollback."""

    def __init__(
        self,
        verbose_getter: Callable[[], bool] | None = None,
        status_setter: Callable[[str | None], None] | None = None,
    ) -> None:
        self.name: str = "agent"
        self.model: str | None = None
        self.max_turns: int | None = None
        self.depth: int = 0
        self.finish_params: Any = None
        self.run_metadata: dict[str, list[Any]] | None = None
        self.output_dir: str | None = None
        self._verbose_getter = verbose_getter or (lambda: False)
        self._status_setter = status_setter or (lambda name: None)
        self.turn_input_tokens: int = 0
        self.turn_output_tokens: int = 0
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self._consecutive_text_only: int = 0

    def reset_turn_tokens(self) -> None:
        self.total_input_tokens += self.turn_input_tokens
        self.total_output_tokens += self.turn_output_tokens
        self.turn_input_tokens = 0
        self.turn_output_tokens = 0

    def reset_runaway_counter(self) -> None:
        self._consecutive_text_only = 0

    def __enter__(self) -> "ChatAgentLogger":
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: object) -> None:
        return None

    def on_step(self, step: int, tool_calls: int = 0, input_tokens: int = 0, output_tokens: int = 0) -> None:
        self.turn_input_tokens = input_tokens
        self.turn_output_tokens = output_tokens

    def assistant_message(self, turn: int, max_turns: int, assistant_message: AssistantMessage) -> None:
        text = render_assistant_text(assistant_message)
        if text is None and not assistant_message.tool_calls:
            return
        console.print()  # blank line separates each step from the block above it
        if text is not None:
            console.print(text)
        for tool_call in assistant_message.tool_calls:
            console.print(render_tool_call_line(tool_call))
            self._status_setter(tool_call.name)

        if assistant_message.tool_calls:
            self._consecutive_text_only = 0
        else:
            self._consecutive_text_only += 1
            if self._consecutive_text_only >= _RUNAWAY_TEXT_ONLY_THRESHOLD:
                console.print(render_system_note(
                    "⏹ 模型连续多次纯文本回答未调用 finish 工具，已自动中断本轮。"
                ))
                self._consecutive_text_only = 0
                raise RunawayLoopError("agent produced consecutive text-only replies without finishing")

    def user_message(self, user_message: UserMessage) -> None:
        # The chat UI already echoes the user's own text on submit — avoid double-printing.
        pass

    def task_message(self, task: str | list[Any]) -> None:
        # The user's first message already appears as a chat bubble; no separate framing needed.
        pass

    def tool_result(self, tool_message: ToolMessage) -> None:
        console.print(render_tool_result_block(tool_message, expanded=self._verbose_getter()))
        self._status_setter(None)

    def context_summarization_start(self, pct_used: float, cutoff: float) -> None:
        console.print(render_system_note(f"context window at {pct_used:.0%}, summarizing…"))

    def context_summarization_complete(self, summary: str, bridge: str) -> None:
        console.print(render_context_summarization_note())

    def debug(self, message: str, *args: object) -> None:
        pass  # too noisy for the chat pane

    def info(self, message: str, *args: object) -> None:
        formatted = message % args if args else message
        if any(n in formatted for n in _NOISE):
            return
        console.print(render_system_note(formatted))

    def warning(self, message: str, *args: object) -> None:
        formatted = message % args if args else message
        if any(n in formatted for n in _NOISE):
            return
        console.print(Text.from_markup(f"[yellow]⚠ {formatted}[/yellow]"))

    def error(self, message: str, *args: object) -> None:
        formatted = message % args if args else message
        console.print(Text.from_markup(f"[red]✗ {formatted}[/red]"))
