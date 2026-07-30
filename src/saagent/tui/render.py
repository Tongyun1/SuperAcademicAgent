"""Pure functions: agent/tool messages -> Rich renderables for the chat transcript.

Claude-Code-style transcript: no panels/boxes, just "⏺ "-prefixed lines printed straight
into real terminal scrollback. Tool results are collapsed to their first HEAD_CHARS
characters by default; ChatSession's global verbose toggle (Ctrl+O) switches future tool
results to print in full — see tui/app.py and tui/logger.py.
"""

from __future__ import annotations

import html
import json

from rich.console import RenderableType
from rich.rule import Rule
from rich.text import Text
from stirrup import AssistantMessage, ToolCall, ToolMessage

HEAD_CHARS = 500


def render_assistant_text(assistant_message: AssistantMessage) -> RenderableType | None:
    content = assistant_message.content
    if isinstance(content, list):
        content = "\n".join(str(block) for block in content)
    if not content or not content.strip():
        return None
    if len(content) > 2000:
        content = content[:2000] + "…"

    body = Text()
    lines = content.splitlines()
    for i, line in enumerate(lines):
        body.append("⏺ " if i == 0 else "  ", style="bold white")
        body.append(line, style="white")
        if i != len(lines) - 1:
            body.append("\n")
    return body


def _format_call_args(arguments: str, *, max_len: int = 80) -> str:
    if not arguments or not arguments.strip():
        return ""
    try:
        parsed = json.loads(arguments)
    except (json.JSONDecodeError, TypeError):
        summary = arguments
    else:
        if isinstance(parsed, dict):
            parts = []
            for k, v in parsed.items():
                v_str = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
                parts.append(v_str if len(parsed) == 1 else f"{k}={v_str}")
            summary = ", ".join(parts)
        else:
            summary = json.dumps(parsed, ensure_ascii=False)

    summary = summary.replace("\n", " ")
    if len(summary) > max_len:
        summary = summary[:max_len] + "…"
    return summary


def render_tool_call_line(tool_call: ToolCall) -> RenderableType:
    summary = _format_call_args(tool_call.arguments)
    line = Text()
    line.append("⏺ ", style="bold cyan")
    line.append(tool_call.name, style="bold")
    line.append(f"({summary})", style="dim")
    return line


def render_tool_result_block(tool_message: ToolMessage, *, expanded: bool = False) -> RenderableType:
    text = tool_message.content
    if isinstance(text, list):
        text = "\n".join(str(block) for block in text)
    text = html.unescape(text)

    truncated = not expanded and len(text) > HEAD_CHARS
    shown = text[:HEAD_CHARS] if truncated else text
    lines = shown.splitlines() or [""]

    style = "red" if not tool_message.args_was_valid else "grey70"
    body = Text()
    for i, line in enumerate(lines):
        body.append("  ⎿ " if i == 0 else "     ", style="dim")
        body.append(line, style=style)
        body.append("\n")
    if truncated:
        remaining = len(text) - HEAD_CHARS
        body.append(f"     … +{remaining} chars (ctrl+o to expand)", style="dim italic")
    else:
        body = body[: len(body) - 1]

    return body


def render_user_message(text: str) -> RenderableType:
    if len(text) > 2000:
        text = text[:2000] + "…"
    line = Text()
    line.append("❯ ", style="bold blue")
    line.append(text, style="white")
    return line


def render_system_note(text: str) -> RenderableType:
    return Text.from_markup(f"[dim italic]· {text}[/dim italic]")


def render_question_prompt(question: str, choices: list[str] | None) -> RenderableType:
    body = Text()
    body.append("⏺ ", style="bold magenta")
    body.append(question, style="bold cyan")
    if choices:
        for i, c in enumerate(choices, 1):
            body.append(f"\n  {i}. {c}", style="cyan")
    return body


def render_answer_echo(answer: str) -> RenderableType:
    line = Text()
    line.append("❯ ", style="bold blue")
    line.append(answer, style="white")
    return line


def render_context_summarization_note() -> RenderableType:
    return Rule("[dim]context summarized[/dim]", style="dim")
