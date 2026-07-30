"""Shared post-run finalization: localize + export, for both `saagent run` and the chat UI.

Extracted from cli.py::_run so ChatApp._run_turn (saagent.tui.app) can call the exact same
localize + export_all logic after `emit_result`, instead of duplicating it.
"""

from __future__ import annotations

import time

from .context import RunContext
from .engine.cli import console
from .engine.export import export_all


def finalize_result(ctx: RunContext, *, no_translate: bool) -> dict[str, str] | None:
    """Localize the report to zh (best-effort) and export all artifacts.

    Call only when ctx.result is not None (i.e. emit_result has been called).
    Returns the exported-paths dict (or a minimal {"json": ...} fallback / None),
    matching the exact try/except-swallow semantics `_run()` used to inline.
    """
    if not no_translate and getattr(ctx.settings, "translate", True) and ctx.result.report:
        try:
            from saagent.engine.core.translate import localize
            console.print("  [dim yellow]⏳ 正在翻译报告为中文（可能需要 20-60 秒，界面暂停响应）…[/dim yellow]")
            t0 = time.time()
            localize(ctx.result, ctx.llm, "zh")
            console.print(f"  [dim green]✓ 翻译完成（用时 {time.time() - t0:.1f}s）[/dim green]")
        except Exception as e:  # noqa: BLE001 — translation is best-effort
            console.print(f"  [dim yellow]localize skipped: {e}[/dim yellow]")

    try:
        console.print("  [dim yellow]⏳ 正在生成 HTML / PNG / GraphML 等产出文件…[/dim yellow]")
        t0 = time.time()
        exported = export_all(ctx.result, str(ctx.out_dir))
        console.print(f"  [dim green]✓ 导出完成（用时 {time.time() - t0:.1f}s）[/dim green]")
        return exported
    except Exception as e:  # noqa: BLE001
        console.print(f"  [dim yellow]export skipped: {e}[/dim yellow]")
        return {"json": ctx.result_path} if ctx.result_path else None
