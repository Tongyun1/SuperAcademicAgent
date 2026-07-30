"""Step C2: locate the founding / seminal paper(s)."""
from __future__ import annotations

from ..llm.base import LLMClient
from ..llm.prompts import pick_founding
from ..models import CitationGraph
from .graph import _norm


def _foundational_scores(graph: CitationGraph) -> dict[str, float]:
    """Blend: well-cited within the network (pagerank) + globally cited + older."""
    pr = {n.paper_id: n.metrics.get("pagerank", 0.0) for n in graph.nodes}
    cites = {n.paper_id: float(n.citation_count) for n in graph.nodes}
    years = {n.paper_id: n.year for n in graph.nodes if n.year}
    npr, ncite = _norm(pr), _norm(cites)
    # recency: older -> higher
    if years:
        ymin, ymax = min(years.values()), max(years.values())
        span = max(ymax - ymin, 1)
        old = {pid: (ymax - y) / span for pid, y in years.items()}
    else:
        old = {}
    # down-weight "old": over-weighting age dredges up tangential 1990s papers
    scores = {}
    for n in graph.nodes:
        scores[n.paper_id] = (
            0.50 * npr.get(n.paper_id, 0.0)
            + 0.35 * ncite.get(n.paper_id, 0.0)
            + 0.15 * old.get(n.paper_id, 0.0)
        )
    return scores


def find_founding(
    graph: CitationGraph,
    llm: LLMClient,
    query: str,
    top_k: int = 3,
) -> list[str]:
    scores = _foundational_scores(graph)
    if not scores:
        return []
    # founding must be ON-TOPIC: restrict to core nodes (fall back if too few tagged)
    core = [n for n in graph.nodes if n.metrics.get("relevance") == "core"]
    pool_nodes = core if len(core) >= 3 else graph.nodes
    ranked = sorted(pool_nodes, key=lambda n: scores[n.paper_id], reverse=True)
    candidates = ranked[: min(10, len(ranked))]
    # always include the seed paper(s) — the user's anchor must be a candidate
    seed_set = set(graph.seeds)
    in_pool = {n.paper_id for n in candidates}
    for n in graph.nodes:
        if n.paper_id in seed_set and n.paper_id not in in_pool:
            candidates.append(n)

    if llm.available:
        seed_set = set(graph.seeds)
        payload = [
            {
                "id": n.paper_id,
                "title": n.title,
                "year": n.year,
                "citation_count": n.citation_count,
                "cited_in_field": n.metrics.get("in_degree", 0),
                "centrality": round(n.metrics.get("pagerank", 0.0), 4),
                "is_seed": n.paper_id in seed_set,
                "abstract": (graph.papers[n.paper_id].abstract or "")[:500]
                if n.paper_id in graph.papers
                else "",
            }
            for n in candidates
        ]
        seed_title = None
        if graph.seeds and graph.seeds[0] in graph.papers:
            seed_title = graph.papers[graph.seeds[0]].title
        out = llm.complete_json(*pick_founding(query, payload, seed_title=seed_title))
        if isinstance(out, dict) and isinstance(out.get("founding"), list):
            picked = [i for i in out["founding"] if any(n.paper_id == i for n in graph.nodes)]
            if picked:
                _tag(graph, picked)
                return picked[:top_k]

    # heuristic fallback: among the strongest, prefer the earliest
    by_year = sorted(candidates, key=lambda n: (n.year or 9999))
    picked = [n.paper_id for n in by_year[:top_k]]
    _tag(graph, picked)
    return picked


def _tag(graph: CitationGraph, founding_ids: list[str]) -> None:
    fset = set(founding_ids)
    for n in graph.nodes:
        if n.paper_id in fset:
            n.role = "founding"
