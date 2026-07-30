"""Claude-Code-style ask_user: numbered choices, lenient input.

Stirrup's built-in user_input uses rich Prompt(choices=...), which requires the user to
type the FULL exact option string — awful UX for long descriptive options. This executor
shows numbered options and accepts:
  - a number (1..N)         -> that option
  - free text              -> passed back to the model to interpret (e.g. "the AI one")
  - Enter                  -> the default (or first option)
It also tolerates `choices` arriving as a JSON string (some models emit that).
"""

from __future__ import annotations

import json

from pydantic import field_validator
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from stirrup import Tool, ToolResult, ToolUseCountMetadata
from stirrup.tools.user_input import UserInputParams, _get_logger
from stirrup.utils.logging import console


class AskUserParams(UserInputParams):
    """UserInputParams tolerant of `choices` sent as a JSON string or comma list."""

    @field_validator("choices", mode="before")
    @classmethod
    def _coerce_choices(cls, v):
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return [str(x) for x in parsed]
            except Exception:  # noqa: BLE001
                pass
            parts = [s.strip() for s in v.split(",") if s.strip()]
            return parts or None
        return v


def ask_user_executor(params: AskUserParams) -> ToolResult[ToolUseCountMetadata]:
    logger = _get_logger()
    if logger:
        logger.pause_live()
    try:
        console.print()
        console.print(
            Panel(params.question, title="[bold cyan]🤔 Agent Question[/]", title_align="left",
                  border_style="cyan", padding=(0, 1))
        )

        if params.question_type == "confirm":
            default_bool = params.default.lower() in ("yes", "y", "true", "1") if params.default else False
            answer = "yes" if Confirm.ask("[bold]Your answer[/]", default=default_bool, console=console) else "no"

        elif params.question_type == "choice" and params.choices:
            for i, c in enumerate(params.choices, 1):
                console.print(f"  [bold cyan]{i}.[/] {c}")
            raw = Prompt.ask(
                "[bold]Your answer[/] [dim](number, or type your own)[/]",
                default=params.default or "",
                console=console,
            ).strip()
            if raw.isdigit() and 1 <= int(raw) <= len(params.choices):
                answer = params.choices[int(raw) - 1]
            elif raw:
                answer = raw  # free text -> let the model interpret it
            else:
                answer = params.default or params.choices[0]

        else:
            answer = Prompt.ask("[bold]Your answer[/]", default=params.default or "", console=console)

        return ToolResult(content=answer, metadata=ToolUseCountMetadata())
    finally:
        if logger:
            logger.resume_live()


ASK_USER_TOOL: Tool = Tool[AskUserParams, ToolUseCountMetadata](
    name="ask_user",
    description=(
        "Ask the user ONE question when uncertain. question_type: 'text' (free-form), "
        "'choice' (provide a `choices` list — the user can pick by number or type their own), "
        "or 'confirm' (yes/no). Use 'choice' with concrete options when the input is ambiguous. "
        "Do NOT add your own 'type your own answer' / 'other' catch-all entry to `choices` — "
        "the UI already lets the user type free text."
    ),
    parameters=AskUserParams,
    executor=ask_user_executor,
)
