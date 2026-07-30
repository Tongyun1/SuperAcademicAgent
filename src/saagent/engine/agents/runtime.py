"""Minimal agent runtime: a tool-using ReAct loop with a JSON action protocol.

Dependency-free (no LangChain). Works with any LLMClient; the loop degrades
gracefully when the model returns malformed actions.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from ..llm.base import LLMClient, extract_json
from .workspace import Trace


@dataclass
class Tool:
    name: str
    description: str
    args: dict[str, str]  # arg name -> human description
    func: Callable[[dict], Awaitable[str]]  # async (args) -> observation text


@dataclass
class AgentResult:
    final: dict | None
    steps: int
    ok: bool = True


def _tools_doc(tools: list[Tool]) -> str:
    out = []
    for t in tools:
        args = ", ".join(f'"{k}": <{v}>' for k, v in t.args.items()) or "(none)"
        out.append(f"- {t.name}: {t.description}  args: {{{args}}}")
    return "\n".join(out)


_PROTOCOL = (
    'Respond with ONE JSON object only, no prose. To use a tool:\n'
    '  {"thought": "...", "action": "<tool_name>", "args": {...}}\n'
    'When you have enough information, finish:\n'
    '  {"thought": "...", "action": "finish", "args": {<your final result>}}'
)


class Agent:
    """A single role agent that runs a bounded think->act->observe loop."""

    def __init__(
        self,
        name: str,
        system: str,
        llm: LLMClient,
        tools: list[Tool] | None = None,
        trace: Trace | None = None,
        max_steps: int = 8,
    ):
        self.name = name
        self.system = system
        self.llm = llm
        self.tools = {t.name: t for t in (tools or [])}
        self.trace = trace
        self.max_steps = max_steps

    def _log(self, kind: str, content) -> None:
        if self.trace:
            self.trace.add(self.name, kind, content)

    async def _think(self, system: str, prompt: str) -> dict | None:
        # LLM calls are sync; run off-thread so the event loop stays free.
        raw = await asyncio.to_thread(self.llm.complete_text, system, prompt)
        return extract_json(raw)

    async def run(self, goal: str) -> AgentResult:
        if not self.llm.available:
            return AgentResult(final=None, steps=0, ok=False)

        sys = f"{self.system}\n\n{_PROTOCOL}"
        scratch: list[str] = []
        for step in range(self.max_steps):
            prompt = (
                f"Goal:\n{goal}\n\n"
                f"Available tools:\n{_tools_doc(list(self.tools.values()))}\n\n"
                f"History so far:\n{chr(10).join(scratch) if scratch else '(empty)'}\n\n"
                f"Decide the next single step."
            )
            action = await self._think(sys, prompt)
            if not isinstance(action, dict) or "action" not in action:
                self._log("error", "unparseable action; stopping")
                return AgentResult(final=None, steps=step, ok=False)

            thought = action.get("thought", "")
            name = action.get("action")
            args = action.get("args", {}) if isinstance(action.get("args"), dict) else {}
            self._log("thought", thought)

            if name == "finish":
                self._log("finish", args)
                return AgentResult(final=args, steps=step + 1, ok=True)

            tool = self.tools.get(name)
            if tool is None:
                obs = f"ERROR: unknown tool '{name}'. Valid: {list(self.tools)}"
            else:
                self._log("action", {"tool": name, "args": args})
                try:
                    obs = await tool.func(args)
                except Exception as e:  # noqa: BLE001
                    obs = f"ERROR running {name}: {e}"
            self._log("observation", obs[:500])
            scratch.append(f"step {step}: {name}({json.dumps(args, ensure_ascii=False)}) -> {obs[:400]}")

        self._log("note", "max_steps reached")
        return AgentResult(final=None, steps=self.max_steps, ok=False)
