"""Assemble the Stirrup research Agent from a RunContext."""

from __future__ import annotations

import time

import stirrup.core.agent as _stirrup_agent
from rich.spinner import Spinner
from stirrup import Agent, Tool
from stirrup.utils.logging import AgentLogger, AgentLoggerBase

from .client_anthropic import AnthropicMessagesClient
from .client_openai import OpenAICompatClient
from .context import RunContext
from .engine.cli import _fmt_wall
from .prompts import CONTINUATION_ADDENDUM, RESEARCH_AGENT_SYSTEM, ZH_INTERACTION
from .tools import build_emit_result_tool, build_tools

from pydantic import BaseModel, Field
from stirrup import ToolResult, ToolUseCountMetadata


class _DoneParams(BaseModel):
    message: str = Field(default="", description="Optional short note (not shown to user).")


def _build_done_tool(ctx: RunContext) -> Tool:
    """Lightweight finish tool: ends the turn without writing result.json."""
    def _done(p: _DoneParams) -> ToolResult[ToolUseCountMetadata]:
        ctx.set_research_mode(False)
        return ToolResult(content=p.message or "done", metadata=ToolUseCountMetadata(), success=True)

    return Tool[_DoneParams, ToolUseCountMetadata](
        name="done",
        description=(
            "End this turn WITHOUT producing result.json. Use after answering a non-research "
            "question (config, small talk, instructions). Do NOT use this when you have research "
            "results to deliver — use emit_result for that."
        ),
        parameters=_DoneParams,
        executor=_done,
    )


# Long runs can cross Stirrup's own context-summarization threshold. Its bridge text
# ("Context Continuation... Proceed with completing any outstanding work.") becomes the
# MOST RECENT context right before the next generation — recency bias then pulls the
# model back to English even though our system prompt (far earlier in context) says
# Chinese. Append a Chinese reminder to that bridge template so resumption after a
# compaction stays on language. This patches a module-level string constant in the
# installed `stirrup` package (no public hook exists to override it) — low risk since
# it's a plain string, but tied to Stirrup's internal layout and may need re-checking
# after a Stirrup upgrade.
_ZH_SUMMARY_REMINDER = "\n\n请继续用中文与用户交流、说明进展；论文标题等专有名词保持原文。"
_ORIGINAL_BRIDGE_TEMPLATE = _stirrup_agent.MESSAGE_SUMMARIZER_BRIDGE_TEMPLATE


def _patch_summarizer_bridge_for_zh() -> None:
    patched = _ORIGINAL_BRIDGE_TEMPLATE + _ZH_SUMMARY_REMINDER
    if _stirrup_agent.MESSAGE_SUMMARIZER_BRIDGE_TEMPLATE != patched:
        _stirrup_agent.MESSAGE_SUMMARIZER_BRIDGE_TEMPLATE = patched

# Stirrup warns when its default code-exec / web tools are absent. This agent
# deliberately doesn't use them (our tools + emit_result write result.json directly),
# so those warnings are harmless noise. Filter them out; keep any genuine warnings.
_NOISE_WARNINGS = ("Missing default tool", "no code execution tool")


class _TickingSpinnerText:
    """Recomputes the spinner's stats line + elapsed time on every render.

    Stirrup's own spinner text (steps/tool_calls/tokens) only refreshes when
    `on_step()` is called — once per turn, with no wall-clock readout. This
    wraps it so elapsed time ticks continuously: Live's auto-refresh runs on
    its own background thread and calls `__rich__` on every tick, so the
    clock keeps counting even while the main thread is blocked inside a
    synchronous LLM call.
    """

    def __init__(self, logger: "_QuietAgentLogger") -> None:
        self._logger = logger

    def __rich__(self):
        text = self._logger._make_spinner_text()
        elapsed = time.time() - self._logger._started
        text.append("  │  ", style="dim")
        text.append(_fmt_wall(elapsed), style="bold cyan")
        return text


class _QuietAgentLogger(AgentLogger):
    """AgentLogger that drops the 'missing default tool' noise, keeps the rest,
    and adds a ticking elapsed-time readout to the spinner (see _TickingSpinnerText)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._started = time.time()
        self._spinner_obj: Spinner | None = None

    def _make_spinner(self) -> Spinner:
        if self._spinner_obj is None:
            self._spinner_obj = Spinner("aesthetic", text=_TickingSpinnerText(self), style="green")
        return self._spinner_obj

    def warnings_message(self, warnings: list[str]) -> None:
        keep = [w for w in warnings if not any(n in w for n in _NOISE_WARNINGS)]
        if keep:
            super().warnings_message(keep)


def build_client(ctx: RunContext, *, model: str | None = None, max_output_tokens: int = 8192):
    """Pick the Stirrup LLM client for the agent loop based on the configured provider.

    - bailian  -> DashScope OpenAI-compatible endpoint (quota-friendly; default for loops)
    - claude   -> Anthropic-compatible gateway (native tool_use; may be rate-limited — probes only)
    """
    s = ctx.settings
    provider = s.llm_provider
    if provider == "bailian":
        return OpenAICompatClient(
            model=model or s.bailian_model,
            base_url=s.bailian_base_url,
            api_key=s.bailian_api_key,
            max_output_tokens=max_output_tokens,
        )
    # default: Anthropic-compatible gateway
    return AnthropicMessagesClient(model=model or (s.llm_model or "qwen3.7-max"), max_output_tokens=max_output_tokens)


def build_agent(
    ctx: RunContext,
    *,
    model: str | None = None,
    max_turns: int = 999_999,
    max_output_tokens: int = 8192,
    enable_ask_user: bool = True,
    lang: str = "zh",
    logger: AgentLoggerBase | None = None,
    ask_user_tool: Tool | None = None,
) -> Agent:
    """Build a research Agent bound to the run context (shared graph/tools).

    lang controls the language the agent talks to the user in (ask_user / narration);
    the report itself stays English-based and is localized to i18n.zh separately.

    logger/ask_user_tool let the interactive chat UI swap in Textual-bound
    replacements (see saagent.tui); both default to the existing one-shot-CLI
    behavior when omitted, so `saagent run` is unaffected.
    """
    client = build_client(ctx, model=model, max_output_tokens=max_output_tokens)
    if lang == "zh":
        _patch_summarizer_bridge_for_zh()
    system_prompt = RESEARCH_AGENT_SYSTEM + CONTINUATION_ADDENDUM + (ZH_INTERACTION if lang == "zh" else "")
    agent = Agent(
        client=client,
        name="researcher",
        tools=build_tools(ctx, enable_ask_user=enable_ask_user, ask_user_tool=ask_user_tool),
        finish_tool=[build_emit_result_tool(ctx), _build_done_tool(ctx)],
        system_prompt=system_prompt,
        max_turns=max_turns,
        logger=logger if logger is not None else _QuietAgentLogger(),
        block_successive_assistant_messages=False,
    )
    ctx.agent = agent
    return agent
