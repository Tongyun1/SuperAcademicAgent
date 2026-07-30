"""Session config tools: let the user change runtime settings via natural language."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from stirrup import Tool, ToolResult, ToolUseCountMetadata
from stirrup.core.models import EmptyParams

from ..context import RunContext


def _ok(content: str) -> ToolResult[ToolUseCountMetadata]:
    return ToolResult(content=content, metadata=ToolUseCountMetadata(), success=True)


class SetOutputDirParams(BaseModel):
    path: str = Field(description="The desired output directory path. Supports ~ (home) and relative paths.")


class SetConfigParams(BaseModel):
    max_nodes: int | None = Field(default=None, description="Citation network node cap (e.g. 50, 100). Takes effect immediately.")
    lang: Literal["zh", "en"] | None = Field(default=None, description="Agent interaction language. Takes effect on next turn.")
    translate: bool | None = Field(default=None, description="Whether to translate the report to Chinese. True=translate, False=skip.")


_ARTIFACT_NAMES = [
    "result.json", "view.html", "report.md",
    "citation_network.graphml", "roadmap.graphml", "trace.log",
]


def build_config_tools(ctx: RunContext) -> list[Tool]:
    def set_output_dir(p: SetOutputDirParams) -> ToolResult[ToolUseCountMetadata]:
        resolved = Path(p.path).expanduser().resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        old_dir = ctx.out_dir
        ctx.out_dir = resolved

        moved: list[str] = []
        if old_dir and old_dir != resolved:
            for name in _ARTIFACT_NAMES:
                src = old_dir / name
                if src.is_file():
                    shutil.copy2(src, resolved / name)
                    moved.append(name)
            if ctx.result_path and Path(ctx.result_path).parent == old_dir:
                ctx.result_path = str(resolved / "result.json")

        msg = f"Output directory set to: {resolved}"
        if moved:
            msg += f"\nMoved {len(moved)} existing artifact(s): {', '.join(moved)}"
        return _ok(msg)

    def set_config(p: SetConfigParams) -> ToolResult[ToolUseCountMetadata]:
        changes: list[str] = []
        if p.max_nodes is not None:
            ctx.settings.max_nodes = p.max_nodes
            ctx.settings.max_collect = p.max_nodes * 4
            changes.append(f"max_nodes={p.max_nodes}")
        if p.lang is not None:
            ctx.settings._runtime_lang = p.lang
            changes.append(f"lang={p.lang} (next turn)")
        if p.translate is not None:
            ctx.settings.translate = p.translate
            changes.append(f"translate={'on' if p.translate else 'off'}")
        if not changes:
            return _ok("No changes specified.")
        return _ok("Config updated: " + ", ".join(changes))

    def get_config(_p: EmptyParams) -> ToolResult[ToolUseCountMetadata]:
        s = ctx.settings
        lines = [
            f"out_dir: {ctx.out_dir}",
            f"max_nodes: {s.max_nodes}",
            f"lang: {getattr(s, '_runtime_lang', 'zh')}",
            f"translate: {'on' if s.translate else 'off'}",
            f"llm_provider: {s.llm_provider}",
            f"model: {s.llm_model or s.bailian_model}",
        ]
        return _ok("Current config:\n" + "\n".join(lines))

    return [
        Tool[EmptyParams, ToolUseCountMetadata](
            name="get_config",
            description="Show current session settings (output directory, max_nodes, lang, translate, model). Call when the user asks about current config.",
            parameters=EmptyParams,
            executor=get_config,
        ),
        Tool[SetOutputDirParams, ToolUseCountMetadata](
            name="set_output_dir",
            description="Change the output directory where result.json and other artifacts will be written. If results have already been exported, they are copied to the new location. Call this when the user asks to save results to a specific path.",
            parameters=SetOutputDirParams,
            executor=set_output_dir,
        ),
        Tool[SetConfigParams, ToolUseCountMetadata](
            name="set_config",
            description="Change session settings: max_nodes (graph size cap), lang (zh/en), translate (on/off). Call when the user asks to adjust these parameters.",
            parameters=SetConfigParams,
            executor=set_config,
        ),
    ]
