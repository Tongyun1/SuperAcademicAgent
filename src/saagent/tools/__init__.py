"""Tool assembly for the research agent."""

from __future__ import annotations

from stirrup import Tool

from ..context import RunContext
from .analysis import build_analysis_tools
from .ask_user import ASK_USER_TOOL
from .config import build_config_tools
from .emit_result import build_emit_result_tool
from .graph import build_graph_tools
from .notes import build_note_tools
from .read import build_read_tools
from .seeds import build_seed_tools

__all__ = ["build_tools", "build_emit_result_tool", "ASK_USER_TOOL"]


def build_tools(
    ctx: RunContext,
    *,
    enable_ask_user: bool = True,
    ask_user_tool: Tool | None = None,
) -> list[Tool]:
    """All non-finish tools available to the agent for one run.

    ask_user_tool overrides the default static ASK_USER_TOOL — used by the chat
    UI to inject a Textual-bound bridge instead (see saagent.tui.ask_user_bridge).
    """
    tools: list[Tool] = []
    tools.extend(build_seed_tools(ctx))
    tools.extend(build_graph_tools(ctx))
    tools.extend(build_read_tools(ctx))
    tools.extend(build_analysis_tools(ctx))
    tools.extend(build_config_tools(ctx))
    tools.extend(build_note_tools(ctx))
    if enable_ask_user:
        tools.append(ask_user_tool if ask_user_tool is not None else ASK_USER_TOOL)
    return tools
