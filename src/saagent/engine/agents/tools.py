"""Tools the ScoutAgent uses to grow the citation graph (graph-guided exploration)."""
from __future__ import annotations

from ..sources.base import DataSource
from .runtime import Tool
from .workspace import Workspace


def scout_tools(ws: Workspace, source: DataSource) -> list[Tool]:
    s = ws.settings

    async def search(args: dict) -> str:
        q = str(args.get("query") or ws.query)
        hits = await source.search(q, limit=8)
        added = sum(ws.add_paper(p, 1) for p in hits)
        return f"search('{q}'): {len(hits)} hits, {added} new added.\n" + ws.summary()

    async def expand_forward(args: dict) -> str:
        pid = args.get("paper_id")
        if pid not in ws.papers:
            return f"'{pid}' not in graph. Pick a paper_id shown in the summary."
        if pid in ws.expanded_fwd:
            return f"'{pid}' already expanded forward."
        citing = await source.get_citing(pid, s.per_node_citations)
        added = sum(ws.add_paper(p, ws.depth.get(pid, 0) + 1) for p in citing)
        ws.expanded_fwd.add(pid)
        return (
            f"expand_forward({pid}): {len(citing)} citing papers, {added} new added.\n"
            + ws.summary()
        )

    async def expand_backward(args: dict) -> str:
        pid = args.get("paper_id")
        if pid not in ws.papers:
            return f"'{pid}' not in graph."
        if pid in ws.expanded_bwd:
            return f"'{pid}' already expanded backward."
        refs = ws.papers[pid].referenced_works[: s.per_node_references]
        papers = await source.get_many(refs) if refs else []
        added = sum(ws.add_paper(p, ws.depth.get(pid, 0) + 1) for p in papers)
        ws.expanded_bwd.add(pid)
        return (
            f"expand_backward({pid}): {len(refs)} references, {added} new added.\n"
            + ws.summary()
        )

    async def graph_summary(_args: dict) -> str:
        return ws.summary()

    return [
        Tool(
            "search",
            "Free-text search for more papers in this field.",
            {"query": "search string"},
            search,
        ),
        Tool(
            "expand_forward",
            "Fetch papers that CITE a node (newer work) — see how the field developed.",
            {"paper_id": "id from the summary"},
            expand_forward,
        ),
        Tool(
            "expand_backward",
            "Fetch a node's REFERENCES (older work) — trace where ideas came from.",
            {"paper_id": "id from the summary"},
            expand_backward,
        ),
        Tool(
            "graph_summary",
            "Show the current graph state and expansion candidates.",
            {},
            graph_summary,
        ),
    ]
