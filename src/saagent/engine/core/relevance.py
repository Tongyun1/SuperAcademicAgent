"""Topic-relevance tagging: core / related / off-topic per node.

Why: downstream ranking is citation-importance only, so a roadmap drifts to high-citation
general-field papers (GPT-3 for an "on-policy distillation" query) while the niche topic and
its low-citation frontier get buried. Tagging relevance lets us keep the roadmap on the
SPECIFIC topic (core), use general context as background (related), and drop noise (off-topic).
"""
from __future__ import annotations

from ..llm.base import LLMClient
from ..llm.prompts import tag_relevance as _tag_prompt
from ..models import CitationGraph

_VALID = {"core", "related", "off-topic"}


def tag_relevance(graph: CitationGraph, query: str, llm: LLMClient) -> dict:
    """Set node.metrics['relevance'] in place. Returns counts. Neutral default when no LLM."""
    if not graph.nodes:
        return {}
    if not llm.available:
        for n in graph.nodes:
            n.metrics["relevance"] = "related"  # neutral: don't prune in pure-graph mode
        return {"related": len(graph.nodes)}

    payload = [{"id": n.paper_id, "title": n.title, "year": n.year} for n in graph.nodes]
    out = llm.complete_json(*_tag_prompt(query, payload))
    tags = out.get("tags") if isinstance(out, dict) else None
    if not isinstance(tags, dict):
        tags = {}
    counts = {"core": 0, "related": 0, "off-topic": 0}
    for n in graph.nodes:
        t = tags.get(n.paper_id)
        if t not in _VALID:
            t = "related"  # safe default — keep as background, never silently drop
        # never drop a seed: seeds are the user's anchor
        if n.paper_id in graph.seeds and t == "off-topic":
            t = "core"
        n.metrics["relevance"] = t
        counts[t] += 1
    return counts


def prune_off_topic(graph: CitationGraph) -> int:
    """Remove off-topic nodes (and edges touching them) from the graph so the citation
    network / index shown to users stays on-topic. Keeps core + related. Returns #removed.
    Never prunes seeds. No-op if it would empty the graph."""
    keep = {
        n.paper_id
        for n in graph.nodes
        if n.metrics.get("relevance") != "off-topic" or n.paper_id in set(graph.seeds)
    }
    removed = len(graph.nodes) - len(keep)
    if removed <= 0 or not keep:
        return 0
    graph.nodes = [n for n in graph.nodes if n.paper_id in keep]
    graph.edges = [e for e in graph.edges if e.source in keep and e.target in keep]
    graph.papers = {pid: p for pid, p in graph.papers.items() if pid in keep}
    return removed


def prune_noise(graph: CitationGraph, protect: set[str] | None = None, recent_years: int = 2) -> int:
    """Drop peripheral drive-by nodes: OLD papers with 0 citations that are leaves (degree
    <= 1). These are usually tangential works that merely cite a classic (e.g. a random
    old application paper citing "Attention Is All You Need"), not part of the lineage.

    RECENT papers are protected even at 0 citations + leaf: a brand-new follow-up is 0-cite
    *because it is new*, and its citation edges aren't indexed yet — that's exactly the
    frontier we want to keep. Also never drops seeds / founding / `protect`. No-op if it
    would empty the graph. Returns #removed."""
    import datetime

    recent_from = datetime.datetime.now().year - recent_years
    deg: dict[str, int] = {}
    for e in graph.edges:
        deg[e.source] = deg.get(e.source, 0) + 1
        deg[e.target] = deg.get(e.target, 0) + 1
    keep_ids = set(graph.seeds) | (protect or set())
    drop = {
        n.paper_id
        for n in graph.nodes
        if n.paper_id not in keep_ids
        and (n.citation_count or 0) == 0
        and deg.get(n.paper_id, 0) <= 1
        and (n.year or 0) < recent_from  # keep recent 0-cite leaves — they're the frontier
    }
    if not drop or len(drop) >= len(graph.nodes):
        return 0
    graph.nodes = [n for n in graph.nodes if n.paper_id not in drop]
    graph.edges = [e for e in graph.edges if e.source not in drop and e.target not in drop]
    graph.papers = {pid: p for pid, p in graph.papers.items() if pid not in drop}
    return len(drop)
