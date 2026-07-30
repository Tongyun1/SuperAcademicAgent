"""Step C4: AI-filter key papers and build the development roadmap (DAG)."""
from __future__ import annotations

from ..llm.base import LLMClient
from ..llm.prompts import filter_and_roadmap
from ..models import CitationGraph, Roadmap, RoadmapEdge, RoadmapNode
from .graph import _norm


def _importance(graph: CitationGraph) -> dict[str, float]:
    pr = _norm({n.paper_id: n.metrics.get("pagerank", 0.0) for n in graph.nodes})
    btw = _norm({n.paper_id: n.metrics.get("betweenness", 0.0) for n in graph.nodes})
    cite = _norm({n.paper_id: float(n.citation_count) for n in graph.nodes})
    # velocity (citations/age) keeps recent high-impact papers from being crowded
    # out by old high-citation work — so the roadmap/must-read reaches the frontier
    vel = _norm({n.paper_id: n.metrics.get("velocity", 0.0) for n in graph.nodes})
    return {
        n.paper_id: (
            0.40 * pr.get(n.paper_id, 0)
            + 0.25 * btw.get(n.paper_id, 0)
            + 0.10 * cite.get(n.paper_id, 0)
            + 0.25 * vel.get(n.paper_id, 0)
        )
        for n in graph.nodes
    }


def select_key_papers(
    graph: CitationGraph,
    llm: LLMClient,
    query: str,
    founding: list[str] | None = None,
    max_key: int | None = None,  # AI-native: None => the model decides how many
    candidate_pool: int | None = None,  # deprecated: the model now sees the full on-topic set
) -> Roadmap:
    scores = _importance(graph)
    # Candidate set = ALL on-topic nodes (core + related). Related is included on purpose:
    # the field's recent offspring are often tagged 'related' (e.g. GPT-4 / LLaMA / Mamba
    # for "attention"), and its foundational roots often sit in the broader parent field.
    # Pro-max / AI-native: present the FULL on-topic set with rich signals and let the model
    # decide which papers AND how many form the lineage — no pool cap, no heuristic quotas.
    core = [n for n in graph.nodes if n.metrics.get("relevance") == "core"]
    related = [n for n in graph.nodes if n.metrics.get("relevance") == "related"]
    pool = sorted((core + related) or list(graph.nodes), key=lambda n: scores[n.paper_id], reverse=True)

    roles: dict[str, str] = {}
    contributions: dict[str, str] = {}
    chosen_ids: list[str] = []
    llm_edges: list[RoadmapEdge] = []

    if llm.available:
        payload = [
            {
                "id": n.paper_id,
                "title": n.title,
                "year": n.year,
                "citation_count": n.citation_count,
                "velocity": round(n.metrics.get("velocity", 0), 1),  # citations/yr — recency-aware impact
                "pagerank": round(n.metrics.get("pagerank", 0), 4),  # structural importance in the graph
                "relevance": n.metrics.get("relevance"),  # core | related (topic proximity)
            }
            for n in pool
        ]
        out = llm.complete_json(*filter_and_roadmap(query, payload))
        if isinstance(out, dict):
            valid = {n.paper_id for n in graph.nodes}
            for kp in out.get("key_papers", []) or []:
                if isinstance(kp, dict) and kp.get("id") in valid:
                    chosen_ids.append(kp["id"])
                    roles[kp["id"]] = kp.get("role", "normal")
                    contrib = kp.get("contribution")
                    if isinstance(contrib, str) and contrib.strip():
                        contributions[kp["id"]] = contrib.strip()
            for e in out.get("edges", []) or []:
                if isinstance(e, dict) and e.get("source") in valid and e.get("target") in valid:
                    llm_edges.append(
                        RoadmapEdge(
                            source=e["source"], target=e["target"], relation=e.get("relation", "leads_to")
                        )
                    )

    if not chosen_ids:
        # no-LLM fallback only: pick top by importance (a count is needed here since
        # there's no model to decide). Defaults generously; a real degradation policy
        # can tune this later.
        k = min(len(pool), max_key or 25)
        chosen_ids = [n.paper_id for n in pool[:k]]
        roles = _heuristic_roles(graph, chosen_ids)

    # --- unify founding: C2's result is the single source of truth -----------
    founding_set = set(founding or [])
    valid_ids = {n.paper_id for n in graph.nodes}
    # founding papers must appear in the roadmap (prepend any that are missing)
    for fid in founding_set:
        if fid in valid_ids and fid not in chosen_ids:
            chosen_ids.insert(0, fid)
    # exactly the C2 founding papers carry the 'founding' role; downgrade others
    for pid in list(roles):
        if roles[pid] == "founding" and pid not in founding_set:
            roles[pid] = "breakthrough"
    for fid in founding_set:
        roles[fid] = "founding"

    # AI-native: the model decides the count — just dedup, don't truncate to a fixed cap.
    # (max_key, when set, acts only as an optional safety ceiling for degraded modes.)
    chosen_ids = list(dict.fromkeys(chosen_ids))
    if max_key:
        chosen_ids = chosen_ids[:max_key]
    # never drop a founding paper
    for fid in founding_set:
        if fid in valid_ids and fid not in chosen_ids:
            chosen_ids.append(fid)
    chosen_set = set(chosen_ids)

    # apply roles back onto the citation-graph nodes
    for n in graph.nodes:
        if n.paper_id in founding_set:
            n.role = "founding"
        elif n.paper_id in chosen_set:
            n.role = roles.get(n.paper_id, n.role)  # type: ignore[assignment]

    # roadmap nodes ordered chronologically
    rnodes = [
        RoadmapNode(
            paper_id=pid,
            title=graph.papers[pid].title if pid in graph.papers else "",
            year=graph.papers[pid].year if pid in graph.papers else None,
            role=roles.get(pid, "normal"),  # type: ignore[arg-type]
            contribution=contributions.get(pid),
        )
        for pid in chosen_ids
    ]
    rnodes.sort(key=lambda n: (n.year or 9999))

    # edges: prefer LLM evolution edges; else derive from real citations among key papers
    if llm_edges:
        edges = [e for e in llm_edges if e.source in chosen_set and e.target in chosen_set]
    else:
        edges = _citation_edges(graph, chosen_set)

    return Roadmap(nodes=rnodes, edges=edges)


def _heuristic_roles(graph: CitationGraph, ids: list[str]) -> dict[str, str]:
    roles: dict[str, str] = {}
    years = [graph.papers[i].year for i in ids if i in graph.papers and graph.papers[i].year]
    earliest = min(years) if years else None
    for i in ids:
        p = graph.papers.get(i)
        if not p:
            continue
        title = (p.title or "").lower()
        if any(w in title for w in ("survey", "review", "overview")):
            roles[i] = "survey"
        elif p.year == earliest:
            roles[i] = "founding"
        else:
            roles[i] = "breakthrough"
    return roles


def _citation_edges(graph: CitationGraph, chosen: set[str]) -> list[RoadmapEdge]:
    """Influence edge earlier->later whenever a later key paper cites an earlier one."""
    edges: list[RoadmapEdge] = []
    seen: set[tuple[str, str]] = set()
    for e in graph.edges:  # e: citing(source) -> cited(target)
        if e.source in chosen and e.target in chosen:
            later, earlier = e.source, e.target
            ly = graph.papers[later].year or 0
            ey = graph.papers[earlier].year or 0
            if ey <= ly and (earlier, later) not in seen:
                edges.append(RoadmapEdge(source=earlier, target=later, relation="leads_to"))
                seen.add((earlier, later))
    return edges
