"""Thread-safe ask_user handshake for the chat UI.

Stirrup dispatches sync tool executors via anyio.to_thread.run_sync — a plain OS worker
thread with NO running event loop of its own (see stirrup.core.agent's run_tool). It can't
await anything, so it can't talk to the chat session's asyncio loop directly.
concurrent.futures.Future + loop.call_soon_threadsafe is the correct thread-safe bridge:
Future.result() blocks the worker thread (fine, it's not the loop thread); Future.set_result()
from the loop-thread side wakes it back up. asyncio.Future/Event would NOT be safe here since
they're bound to a specific loop and aren't thread-safe to set cross-thread.
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass
from typing import TYPE_CHECKING

from stirrup import Tool, ToolResult, ToolUseCountMetadata

from ..tools.ask_user import AskUserParams

if TYPE_CHECKING:
    from .app import ChatSession


@dataclass
class PendingQuestion:
    question: str
    question_type: str
    choices: list[str] | None
    default: str | None
    future: "concurrent.futures.Future[str]"
    custom_index: int | None = None  # 1-based index of the synthetic "type your own" choice


def _custom_choice_label(lang: str) -> str:
    return "其他（自己输入答案）" if lang == "zh" else "Other (type your own answer)"


def wants_custom_input(pending: PendingQuestion, raw: str) -> bool:
    """True if `raw` selects the synthetic "type your own" choice appended in build_ask_user_tool."""
    raw = raw.strip()
    return pending.custom_index is not None and raw.isdigit() and int(raw) == pending.custom_index


def resolve_answer(pending: PendingQuestion, raw: str) -> str:
    """Numbered-choice / default resolution, ported from tools.ask_user.ask_user_executor
    (same lenient parsing: digit -> indexed choice, free text -> passthrough, empty -> default)."""
    raw = raw.strip()

    if pending.question_type == "confirm":
        default_bool = pending.default.lower() in ("yes", "y", "true", "1") if pending.default else False
        if not raw:
            return "yes" if default_bool else "no"
        if raw.lower() in ("y", "yes", "true", "1"):
            return "yes"
        if raw.lower() in ("n", "no", "false", "0"):
            return "no"
        return "yes" if default_bool else "no"

    if pending.question_type == "choice" and pending.choices:
        if raw.isdigit() and 1 <= int(raw) <= len(pending.choices):
            return pending.choices[int(raw) - 1]
        if raw:
            return raw  # free text -> let the model interpret it
        return pending.default or pending.choices[0]

    return raw or (pending.default or "")


def build_ask_user_tool(session: "ChatSession") -> Tool:
    """The chat UI's replacement for tools.ask_user.ASK_USER_TOOL.

    Same AskUserParams/description as the one-shot CLI's tool; only the executor differs
    (blocks on a concurrent.futures.Future resolved by the chat session instead of real stdin).
    """

    def ask_user_executor(params: AskUserParams) -> ToolResult[ToolUseCountMetadata]:
        fut: concurrent.futures.Future[str] = concurrent.futures.Future()
        choices = list(params.choices) if params.choices else None
        custom_index = None
        if params.question_type == "choice" and choices:
            choices = [*choices, _custom_choice_label(getattr(session._args, "lang", "zh"))]
            custom_index = len(choices)
        pending = PendingQuestion(
            question=params.question,
            question_type=params.question_type,
            choices=choices,
            default=params.default,
            custom_index=custom_index,
            future=fut,
        )
        session._loop.call_soon_threadsafe(session.present_question, pending)
        answer = fut.result()
        return ToolResult(content=answer, metadata=ToolUseCountMetadata())

    return Tool[AskUserParams, ToolUseCountMetadata](
        name="ask_user",
        description=(
            "Ask the user ONE question when uncertain. question_type: 'text' (free-form), "
            "'choice' (provide a `choices` list — the user can pick by number or type their own), "
            "or 'confirm' (yes/no). Use 'choice' with concrete options when the input is ambiguous. "
            "Do NOT add your own 'type your own answer' / 'other' catch-all entry to `choices` — "
            "the UI automatically appends one."
        ),
        parameters=AskUserParams,
        executor=ask_user_executor,
    )
