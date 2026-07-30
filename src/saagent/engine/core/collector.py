"""Step C3: build the citation network by bidirectional BFS from seeds."""
from __future__ import annotations

import asyncio

from ..config import Settings
from ..models import CitationGraph, GraphEdge, GraphNode, Paper
from ..sources.base import DataSource


import datetime

_CUR_YEAR = datetime.datetime.now().year


def _has_title(p: Paper) -> bool:
    """Drop papers whose metadata came back without a usable title."""
    t = (p.title or "").strip()
    return bool(p.id) and bool(t) and t.lower() != "(untitled)"


def _velocity(p: Paper) -> float:
    """Citations per year since publication — age-normalized impact (vs raw count)."""
    if not p.year:
        return float(p.citation_count)
    age = max(_CUR_YEAR - p.year + 1, 1)
    return p.citation_count / age


async def build_graph(
    seeds: list[Paper],
    source: DataSource,
    settings: Settings,
    query: str = "",
    extra_papers: list[Paper] | None = None,
) -> CitationGraph:
    papers: dict[str, Paper] = {}
    depth: dict[str, int] = {}

    for s in seeds:
        if s.id:
            papers[s.id] = s
            depth[s.id] = 0
    frontier = [s.id for s in seeds if s.id]

    # survey-first: inject LLM-curated survey papers (key/frontier works) as nodes
    for p in extra_papers or []:
        if p.id and p.id not in papers and _has_title(p):
            papers[p.id] = p
            depth[p.id] = 1
            frontier.append(p.id)

    for level in range(settings.max_depth):
        if len(papers) >= settings.max_nodes or not frontier:
            break

        # forward: who cites each frontier paper — pull BOTH most-cited (classic
        # influential work) AND newest (the recent frontier raw-citation sort hides)
        tasks = [source.get_citing(pid, settings.per_node_citations, "citations") for pid in frontier]
        if settings.per_node_recent > 0:
            # "recent_cited": last few years, most-cited -> the *important* frontier
            tasks += [source.get_citing(pid, settings.per_node_recent, "recent_cited") for pid in frontier]
        citing_lists = await asyncio.gather(*tasks)

        # backward: gather reference ids we don't have yet
        ref_ids: set[str] = set()
        for pid in frontier:
            for r in papers[pid].referenced_works[: settings.per_node_references]:
                if r and r not in papers:
                    ref_ids.add(r)
        back_papers = await source.get_many(list(ref_ids)) if ref_ids else []

        # collect candidates, dedup, prefer higher citation counts when truncating
        candidates: dict[str, Paper] = {}
        for plist in citing_lists:
            for p in plist:
                if p.id not in papers and _has_title(p):
                    candidates.setdefault(p.id, p)
        for p in back_papers:
            if p.id not in papers and _has_title(p):
                candidates.setdefault(p.id, p)

        # rank by citation VELOCITY (citations/age), not raw count, so recent
        # high-impact papers aren't crowded out by old papers with accrued citations
        ranked = sorted(candidates.values(), key=_velocity, reverse=True)
        new_frontier: list[str] = []
        for p in ranked:
            if len(papers) >= settings.max_nodes:
                break
            papers[p.id] = p
            depth[p.id] = level + 1
            new_frontier.append(p.id)
        frontier = new_frontier

    # build edges from references intersected with the node set (source cites target)
    node_ids = set(papers)
    edges: list[GraphEdge] = []
    seen_edges: set[tuple[str, str]] = set()
    for pid, p in papers.items():
        for r in p.referenced_works:
            if r in node_ids and (pid, r) not in seen_edges:
                edges.append(GraphEdge(source=pid, target=r, type="cites"))
                seen_edges.add((pid, r))

    nodes = [
        GraphNode(
            paper_id=p.id,
            title=p.title,
            year=p.year,
            citation_count=p.citation_count,
            depth=depth.get(p.id, 0),
        )
        for p in papers.values()
    ]

    return CitationGraph(
        query=query,
        seeds=[s.id for s in seeds if s.id],
        nodes=nodes,
        edges=edges,
        papers=papers,
    )
