"""Graph utilities: networkx conversion + metric computation."""
from __future__ import annotations

import datetime

import networkx as nx

from ..models import CitationGraph
from ..util.text import normalize_title

_CUR_YEAR = datetime.datetime.now().year


def dedupe_nodes(graph: CitationGraph) -> int:
    """Merge nodes that represent the SAME paper into one (entity alignment).

    OpenAlex and arXiv often index the same paper under different ids
    (e.g. 'W2626778328' and 'arxiv:1706.03762' both = "Attention Is All You Need"),
    which duplicates it across the graph, roadmap and founding list. We collapse
    them by normalized title (distinctive multi-word titles only, to avoid
    over-merging), keeping the richest node as canonical and redirecting edges,
    seeds and the papers map onto it.

    Call this right after graph construction, before metrics / founding, so all
    downstream stages see a deduplicated graph. Returns the number of nodes merged.
    """
    groups: dict[tuple, list] = {}
    for n in graph.nodes:
        nt = normalize_title(n.title)
        # only merge on titles distinctive enough to identify a paper
        key = ("title", nt) if len(nt) >= 12 and len(nt.split()) >= 2 else ("id", n.paper_id)
        groups.setdefault(key, []).append(n)

    remap: dict[str, str] = {}  # duplicate id -> canonical id
    for group in groups.values():
        if len(group) < 2:
            continue
        # canonical: prefer a non-arXiv (OpenAlex) id, then higher citations, then richer metrics
        canon = sorted(
            group,
            key=lambda n: (n.paper_id.startswith("arxiv:"), -n.citation_count, -len(n.metrics or {})),
        )[0]
        canon.citation_count = max(x.citation_count for x in group)
        canon.year = canon.year or next((x.year for x in group if x.year), None)
        canon.depth = min(x.depth for x in group)
        if canon.role is None:
            canon.role = next((x.role for x in group if x.role), None)
        for n in group:
            if n.paper_id != canon.paper_id:
                remap[n.paper_id] = canon.paper_id

    if not remap:
        return 0

    # drop merged nodes
    graph.nodes = [n for n in graph.nodes if n.paper_id not in remap]

    # redirect edges onto canonical ids; drop self-loops and duplicates
    seen: set[tuple[str, str]] = set()
    new_edges = []
    for e in graph.edges:
        s = remap.get(e.source, e.source)
        t = remap.get(e.target, e.target)
        if s == t or (s, t) in seen:
            continue
        seen.add((s, t))
        e.source, e.target = s, t
        new_edges.append(e)
    graph.edges = new_edges

    # remap seeds (preserve order, unique)
    graph.seeds = list(dict.fromkeys(remap.get(s, s) for s in graph.seeds))

    # merge papers map: fold duplicate Paper into the canonical one
    for old, canon_id in remap.items():
        op = graph.papers.pop(old, None)
        if op is None:
            continue
        cp = graph.papers.get(canon_id)
        if cp is None:
            op.id = canon_id
            graph.papers[canon_id] = op
            continue
        cp.referenced_works = list(dict.fromkeys([*cp.referenced_works, *op.referenced_works]))
        cp.citation_count = max(cp.citation_count, op.citation_count)
        cp.doi = cp.doi or op.doi
        cp.arxiv_url = cp.arxiv_url or op.arxiv_url
        cp.pdf_url = cp.pdf_url or op.pdf_url
        cp.abstract = cp.abstract or op.abstract
        cp.source_ids = {**(op.source_ids or {}), **(cp.source_ids or {})}

    return len(remap)


def to_networkx(graph: CitationGraph) -> nx.DiGraph:
    g = nx.DiGraph()
    for n in graph.nodes:
        g.add_node(n.paper_id, year=n.year, citation_count=n.citation_count)
    for e in graph.edges:
        if e.source in g and e.target in g:
            g.add_edge(e.source, e.target)  # citing -> cited
    return g


def compute_metrics(graph: CitationGraph) -> nx.DiGraph:
    """Fill node.metrics with pagerank / in-degree / betweenness (in place)."""
    g = to_networkx(graph)
    if g.number_of_nodes() == 0:
        return g

    pr = _pagerank_safe(g)

    indeg = dict(g.in_degree())  # how many network papers cite this one

    if g.number_of_nodes() <= 600:
        try:
            btw = nx.betweenness_centrality(g)
        except (ImportError, RuntimeError, ValueError):
            btw = {n: 0.0 for n in g.nodes}
    else:
        btw = {n: 0.0 for n in g.nodes}

    for n in graph.nodes:
        age = max(_CUR_YEAR - n.year + 1, 1) if n.year else 1
        # merge (not replace) so prior keys like 'relevance' / 'year_raw' survive recompute
        n.metrics.update({
            "pagerank": round(pr.get(n.paper_id, 0.0), 6),
            "in_degree": indeg.get(n.paper_id, 0),
            "betweenness": round(btw.get(n.paper_id, 0.0), 6),
            "velocity": round(n.citation_count / age, 2),  # age-normalized impact
        })
    return g


def _pagerank_safe(g: nx.DiGraph) -> dict[str, float]:
    """nx.pagerank silently picks a scipy backend on modern networkx; when numpy/scipy
    are missing it throws ImportError, the old broad-except swallowed it and every node
    ended up with pagerank=0 -- downstream founding/filter/must-read ordering all broke.
    We try the default impl first, then fall back to a pure-Python power iteration so
    the metric stays useful even without scientific deps installed.
    """
    try:
        return nx.pagerank(g, max_iter=200)
    except (ImportError, ModuleNotFoundError):
        pass
    except (RuntimeError, ValueError):
        pass
    return _pagerank_python(g)


def _pagerank_python(
    g: nx.DiGraph, alpha: float = 0.85, max_iter: int = 200, tol: float = 1.0e-6
) -> dict[str, float]:
    """Pure-Python PageRank power iteration; no numpy/scipy required."""
    n = g.number_of_nodes()
    if n == 0:
        return {}
    x = dict.fromkeys(g, 1.0 / n)
    out_deg = {node: g.out_degree(node) for node in g}
    dangling_nodes = [node for node, deg in out_deg.items() if deg == 0]
    base = (1.0 - alpha) / n
    for _ in range(max_iter):
        x_last = x
        dangling_sum = alpha * sum(x_last[node] for node in dangling_nodes) / n
        x = {node: base + dangling_sum for node in g}
        for node, xn in x_last.items():
            deg = out_deg[node]
            if deg == 0:
                continue
            share = alpha * xn / deg
            for nbr in g.successors(node):
                x[nbr] += share
        err = sum(abs(x[node] - x_last[node]) for node in x)
        if err < n * tol:
            break
    return x


def clean_years(graph: CitationGraph) -> int:
    """Fix dirty publication years using a graph-internal invariant (no external API).

    A cited paper must not be published after the papers citing it. Where a node's
    year is later than the earliest year among its citers, cap it to that earliest
    citer year. This catches re-index errors like 'Attention Is All You Need = 2025'
    (it is cited by many 2018-2022 papers, so 2025 is impossible).

    Returns the number of corrected papers. Corrections are recorded in
    node.metrics['year_raw'] / paper.source_ids['year_raw'].
    """
    # citers[target] = list of citing-paper ids  (edge: source cites target)
    citers: dict[str, list[str]] = {}
    for e in graph.edges:
        citers.setdefault(e.target, []).append(e.source)

    years = {p.id: p.year for p in graph.papers.values() if p.year}
    corrected = 0
    for n in graph.nodes:
        p = graph.papers.get(n.paper_id)
        if not p or not p.year:
            continue
        citer_years = [years[c] for c in citers.get(n.paper_id, []) if c in years]
        if not citer_years:
            continue
        earliest_citer = min(citer_years)
        if p.year > earliest_citer:
            raw = p.year
            p.year = earliest_citer
            n.year = earliest_citer
            p.source_ids = {**p.source_ids, "year_raw": raw}
            n.metrics = {**n.metrics, "year_raw": raw}
            corrected += 1
    return corrected


def _norm(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    lo = min(values.values())
    hi = max(values.values())
    if hi <= lo:
        return {k: 0.0 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}
