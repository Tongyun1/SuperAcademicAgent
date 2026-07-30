"""Rendering utilities shared with the real CLI (saagent.cli).

This module used to also host a standalone Typer CLI that ran the deterministic
pipeline directly (`app`/`run()`), duplicating what `saagent.cli`'s agent loop and
`_run_pipeline()` fallback already do. That command was never registered as a
console script (only `saagent = "saagent.cli:main"` is) and so was unreachable —
removed. What's left is the splash screen, run-id, and run-summary renderers that
`saagent.cli` imports directly.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from rich.console import Console, Group, RenderableType
from rich.rule import Rule
from rich.text import Text

# highlight=False suppresses Rich's automatic number / path / paren coloring,
# which otherwise breaks layout like '2026-06-30' or '6,576 cites' into ugly
# rainbow fragments. We do all coloring ourselves via markup.
console = Console(highlight=False, record=True)


# ─────────────────────────────────────────────────────────────────────
# SPLASH
# ─────────────────────────────────────────────────────────────────────

# Asymmetric star map (left) + SUPERACADEMIC wordmark (right).
# Sized for default 80-col terminals: star map ~28 cols, wordmark ~38 cols.
_SPLASH_LINES = [
    ("       ·   ✦                ", "       ┌─┐┬ ┬┌─┐┌─┐┬─┐┌─┐┌─┐┌─┐┌┬┐┌─┐┌┬┐┬┌─┐"),
    ("  ★          ·              ", "       └─┐│ │├─┘├┤ ├┬┘├─┤│  ├─┤ │││├┤ │││││ "),
    ("       ·    ◆     ★         ", "       └─┘└─┘┴  └─┘┴└─┴ ┴└─┘┴ ┴─┴┘└─┘┴ ┴┴└─┘"),
    ("  ·            ·            ", " p r e c i s e · r i g o r o u s · g r o u n d e d"),
    ("        ✦       ·           ", "                                       "),
]

_LOGO_STYLES = {
    "◆": "bold yellow",
    "✦": "yellow",
    "★": "bright_white",
    "·": "dim",
}


def _splash() -> Text:
    """Asymmetric star field (left) + SUPERACADEMIC wordmark (right)."""
    out = Text()
    for i, (left, right) in enumerate(_SPLASH_LINES):
        for ch in left:
            style = _LOGO_STYLES.get(ch)
            if style:
                out.append(ch, style=style)
            else:
                out.append(ch)
        if i == 3:
            # tagline: italic; first letter of each word colored (orange, green, blue)
            # words in the spaced tagline are separated by "  ·  "
            words = right.split("·")
            _colors = iter(["dark_orange", "green", "blue"])
            for wi, word in enumerate(words):
                if wi > 0:
                    out.append("·", style="dim italic")
                color = next(_colors, None) if word.strip() else None
                first_letter = True
                for ch in word:
                    if ch == " ":
                        out.append(ch)
                    elif first_letter and color:
                        out.append(ch, style=f"bold {color} italic")
                        first_letter = False
                    else:
                        out.append(ch, style="dim italic")
                        first_letter = False
        else:
            out.append(right, style="bold cyan")
        out.append("\n")
    return out


def _short_run_id(query: str, started_at: datetime) -> str:
    h = hashlib.md5(f"{query}|{started_at.isoformat()}".encode()).hexdigest()
    return h[:4]


# ─────────────────────────────────────────────────────────────────────
# RUN SUMMARY & ARTIFACTS PAGE
# ─────────────────────────────────────────────────────────────────────

_ARTIFACT_BLURBS = {
    "json":    "single source of truth",
    "html":    "open in browser — interactive",
    "report":  "human-readable Markdown",
    "graphml": "import to Gephi / Cytoscape",
    "roadmap": "roadmap as GraphML",
    "trace":   "agent decision / verification log",
}


def _fmt_size(path: str) -> str:
    try:
        sz = Path(path).stat().st_size
    except OSError:
        return ""
    if sz >= 1024 * 1024:
        return f"{sz / 1024 / 1024:.1f}M"
    if sz >= 1024:
        return f"{sz / 1024:.0f}K"
    return f"{sz}B"


def _fmt_wall(secs: float) -> str:
    secs = int(secs)
    mm, ss = divmod(secs, 60)
    hh, mm = divmod(mm, 60)
    if hh:
        return f"{hh}h {mm:02d}m {ss:02d}s"
    if mm:
        return f"{mm}m {ss:02d}s"
    return f"{ss}s"


def build_run_summary_renderable(
    result,
    *,
    run_id: str,
    wall_seconds: float,
    exported_paths: dict[str, str] | None,
    out_dir: str | None,
) -> RenderableType:
    """Build the RUN SUMMARY card as a single Rich renderable (no printing).

    Split out from _print_run_summary so both the one-shot CLI (console.print)
    and the chat UI (history_log.write) can share the exact same card, instead
    of maintaining two copies of this rendering logic.
    """
    items: list[RenderableType] = []
    items.append(Rule(style="bold cyan"))
    head = (
        f"  [bold]RUN SUMMARY[/bold]  [dim]·[/dim]  [cyan]#{run_id}[/cyan]"
        f"{' ' * 30}[bold green]✔  COMPLETED[/bold green]"
    )
    items.append(Text.from_markup(head))
    items.append(Rule(style="dim"))

    g = result.graph
    rows = [
        ("wall time",  _fmt_wall(wall_seconds)),
        ("network",    f"{len(g.nodes)} nodes  ·  {len(g.edges)} edges"),
        ("roadmap",    f"{len(result.roadmap.nodes)} papers"),
        ("founding",   f"{len(result.founding)} paper(s)"),
        ("llm",        f"{'on' if result.llm_used else 'off'}"
                       f"{'  (agentic + adversarial verify)' if result.agentic else ''}"),
        ("trace",      f"{len(result.trace)} agent events" if result.trace else "—"),
    ]
    for k, v in rows:
        items.append(Text.from_markup(f"  [dim]{k:<10}[/dim]  {v}"))

    if exported_paths:
        items.append(Rule(style="dim"))
        items.append(Text.from_markup(f"  [bold]ARTIFACTS[/bold]  [dim]·[/dim]  [dim]{out_dir or ''}[/dim]"))
        order = ["json", "html", "report", "graphml", "roadmap", "trace"]
        keys = [k for k in order if k in exported_paths] + [
            k for k in exported_paths if k not in order
        ]
        for k in keys:
            path = exported_paths[k]
            fname = Path(path).name
            size = _fmt_size(path)
            blurb = _ARTIFACT_BLURBS.get(k, "")
            items.append(Text.from_markup(
                f"    [cyan]▸[/cyan]  [bold]{fname:<28}[/bold]"
                f"  [dim]{size:>6}[/dim]   [dim italic]{blurb}[/dim italic]"
            ))

    items.append(Rule(style="dim"))
    items.append(Text.from_markup(f"  [bold]NEXT[/bold]"))
    if exported_paths and "html" in exported_paths:
        items.append(Text.from_markup(
            f"     [cyan]›[/cyan]  open  [bold cyan]{exported_paths['html']}[/bold cyan]"
        ))
    if exported_paths and "report" in exported_paths:
        items.append(Text.from_markup(
            f"     [cyan]›[/cyan]  read  [bold cyan]{exported_paths['report']}[/bold cyan]"
        ))
    qslug = (result.query or "")[:42]
    items.append(Text.from_markup(
        f"     [cyan]›[/cyan]  cite this run:  "
        f"[dim italic]SuperAcademic.run(\"{qslug}\", run=#{run_id})[/dim italic]"
    ))
    items.append(Rule(style="bold cyan"))
    return Group(*items)


def _print_run_summary(
    result,
    *,
    run_id: str,
    wall_seconds: float,
    exported_paths: dict[str, str] | None,
    out_dir: str | None,
) -> None:
    console.print()
    console.print(build_run_summary_renderable(
        result, run_id=run_id, wall_seconds=wall_seconds,
        exported_paths=exported_paths, out_dir=out_dir,
    ))
    console.print()
