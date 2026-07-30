"""Session persistence: save / load / list for the --resume / --continue feature.

Writes a `session.json` into the session's out_dir after every turn, containing
workspace state, conversation history, results slots, and args — enough to fully
resume a cold-start session and continue expanding/reading the graph.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from ..context import ReadingNote, RunContext
from ..engine.models import FieldReport, Paper, Roadmap


SESSION_FILE = "session.json"
SESSION_VERSION = 1


def save_session(
    ctx: RunContext,
    conversation_history: list,
    *,
    args: Any,
    turn_count: int,
    run_id: str | None = None,
    created_at: str | None = None,
) -> Path:
    """Atomically write session.json to ctx.out_dir."""

    now = datetime.now().isoformat(timespec="seconds")
    ws = ctx.ws

    state: dict = {
        "version": SESSION_VERSION,
        "created_at": created_at or now,
        "updated_at": now,
        "run_id": run_id,
        "turn_count": turn_count,
        "args": {
            "model": getattr(args, "model", None),
            "max_nodes": getattr(args, "max_nodes", 60),
            "depth": getattr(args, "depth", 2),
            "lang": getattr(args, "lang", "zh"),
            "no_translate": getattr(args, "no_translate", False),
        },
        "workspace": {
            "query": ws.query,
            "papers": {pid: p.model_dump(mode="json") for pid, p in ws.papers.items()},
            "depth": ws.depth,
            "seeds": ws.seeds,
            "expanded_fwd": list(ws.expanded_fwd),
            "expanded_bwd": list(ws.expanded_bwd),
            "link_attempted": list(ws.link_attempted),
        },
        "results": {
            "founding": list(ctx.founding),
            "roadmap": ctx.roadmap.model_dump(mode="json"),
            "report": ctx.report.model_dump(mode="json"),
            "reading_notes": [
                asdict(n) for n in ctx.reading_notes
            ],
        },
        "trace": ws.trace.dump(),
        "conversation": [m.model_dump(mode="json") for m in conversation_history],
    }

    out_path = ctx.out_dir / SESSION_FILE
    tmp_path = out_path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(state, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(tmp_path, out_path)
    return out_path


def load_session(session_dir: str | Path) -> dict:
    """Load and validate a session.json, returning the raw dict.

    Raises FileNotFoundError if session.json doesn't exist, ValueError if version mismatch.
    """
    path = Path(session_dir) / SESSION_FILE
    if not path.exists():
        raise FileNotFoundError(f"No {SESSION_FILE} in {session_dir} (old session format, cannot resume)")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version", 0) != SESSION_VERSION:
        raise ValueError(f"Unsupported session version: {data.get('version')} (expected {SESSION_VERSION})")
    return data


def restore_workspace(ctx: RunContext, saved: dict) -> None:
    """Overwrite ctx.ws fields from saved workspace state."""
    ws_data = saved["workspace"]
    ws = ctx.ws

    ws.query = ws_data["query"]
    ws.papers = {pid: Paper.model_validate(d) for pid, d in ws_data["papers"].items()}
    ws.depth = {pid: int(d) for pid, d in ws_data["depth"].items()}
    ws.seeds = ws_data["seeds"]
    ws.expanded_fwd = set(ws_data["expanded_fwd"])
    ws.expanded_bwd = set(ws_data["expanded_bwd"])
    ws.link_attempted = set(ws_data["link_attempted"])
    ws.trace.events = saved.get("trace", [])


def restore_results(ctx: RunContext, saved: dict) -> None:
    """Restore founding/roadmap/report/reading_notes from saved state."""
    results = saved["results"]
    ctx.founding = results.get("founding", [])
    ctx.roadmap = Roadmap.model_validate(results.get("roadmap", {}))
    ctx.report = FieldReport.model_validate(results.get("report", {}))
    ctx.reading_notes = [
        ReadingNote(**n) for n in results.get("reading_notes", [])
    ]


def list_sessions(base_dir: str | Path | None = None) -> list[dict]:
    """List available sessions sorted by updated_at (newest first).

    Returns list of dicts: {path, query, updated_at, turn_count, node_count}.
    """
    if base_dir is None:
        base_dir = Path.home() / ".saagent" / "sessions"
    base_dir = Path(base_dir)
    if not base_dir.exists():
        return []

    sessions = []
    for d in base_dir.iterdir():
        if not d.is_dir():
            continue
        sf = d / SESSION_FILE
        if not sf.exists():
            continue
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            sessions.append({
                "path": str(d),
                "query": data.get("workspace", {}).get("query", "?"),
                "updated_at": data.get("updated_at", ""),
                "turn_count": data.get("turn_count", 0),
                "node_count": len(data.get("workspace", {}).get("papers", {})),
            })
        except (json.JSONDecodeError, KeyError):
            continue

    sessions.sort(key=lambda s: s["updated_at"], reverse=True)
    return sessions
