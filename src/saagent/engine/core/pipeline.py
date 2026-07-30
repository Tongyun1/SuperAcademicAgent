"""End-to-end orchestration: query -> founding -> graph -> roadmap -> report."""
from __future__ import annotations

import asyncio

from ..config import Settings
from ..llm import build_llm
from ..models import PipelineResult
from ..sources import OpenAlexSource
from ..store import Cache
from .analyzer import analyze
from .collector import build_graph
from .filter import select_key_papers
from .founding import find_founding
from .graph import clean_years, compute_metrics, dedupe_nodes
from .resolver import resolve


def run(
    query: str,
    *,
    depth: int | None = None,
    max_nodes: int | None = None,
    n_seeds: int = 1,
    agent: bool = False,
    settings: Settings | None = None,
    progress=None,
    on_event=None,
    **overrides,
) -> PipelineResult:
    """Run the full pipeline synchronously. `progress` is an optional callable(str).

    agent=True uses the agentic orchestrator (graph-guided scouting + adversarial
    verification + self-correction); otherwise the deterministic pipeline runs.
    """
    s = settings or Settings.from_env(max_depth=depth, max_nodes=max_nodes, **overrides)

    def log(msg: str):
        if progress:
            progress(msg)

    cache = Cache(s.cache_path, enabled=s.use_cache)
    llm = build_llm(s)
    log(f"LLM: {'on (' + (llm.__class__.__name__) + ')' if llm.available else 'off (pure graph mode)'}")

    if agent:
        import asyncio as _asyncio

        from ..agents import run_agentic

        log("Mode: AGENTIC orchestration")

        async def _agentic():
            source = OpenAlexSource(s, cache)
            try:
                return await run_agentic(
                    query, source, llm, s, progress=log, on_event=on_event
                )
            finally:
                await source.aclose()

        result = _asyncio.run(_agentic())
        cache.close()
        return result

    async def _collect():
        source = OpenAlexSource(s, cache)
        from ..sources.arxiv import ArxivSource

        arxiv = ArxivSource()
        try:
            log("Resolving input -> seeds (dual-source, relevance-gated) ...")
            nq, seeds = await resolve(
                query, source, llm, n_seeds=n_seeds, arxiv=arxiv, on_event=on_event
            )
            if not seeds:
                return nq, [], None
            log(f"Seeds: {', '.join(p.title[:50] for p in seeds)}")
            extra: list = []
            if s.use_surveys and llm.available:
                log("Survey-first: mining recent surveys & curating references ...")
                from .surveys import curate_survey_papers

                extra = await curate_survey_papers(nq, source, llm, s)
                if extra:
                    log(f"Survey-curated {len(extra)} field papers")
            # broad arXiv topic recall: surface recent same-topic papers that citation
            # search misses (arXiv seeds have no OpenAlex forward edges). Off-topic ones
            # get pruned later by relevance tagging.
            if s.arxiv_recall > 0:
                recent_topic = await arxiv.search(nq, max_results=s.arxiv_recall, sort="relevance")
                if recent_topic:
                    log(f"arXiv topic recall: +{len(recent_topic)} recent papers")
                    extra = extra + recent_topic

            # frontier: recent arXiv seeds are citation-disconnected -> recover lineage
            # from their full text (the connection comes from text, not the citation graph)
            frontier_seeds = [p for p in seeds if p.source_ids.get("arxiv")]
            if frontier_seeds and llm.available:
                log("Frontier: reading seed full-text to recover lineage ...")
                from .frontier import link_frontier_papers

                fr = await link_frontier_papers(frontier_seeds, source, arxiv, llm, s, on_event=on_event)
                if fr:
                    log(f"Frontier-linked {len(fr)} predecessors via full-text")
                    extra = extra + fr
            log(f"Building citation network (depth={s.max_depth}, max_nodes={s.max_nodes}) ...")
            graph = await build_graph(seeds, source, s, query=nq, extra_papers=extra)
            return nq, seeds, graph
        finally:
            await source.aclose()
            await arxiv.aclose()

    nq, seeds, graph = asyncio.run(_collect())
    if graph is None or not graph.nodes:
        raise RuntimeError(f"No papers found for query: {query!r}")

    dups = dedupe_nodes(graph)
    if dups:
        log(f"Entity alignment: merged {dups} duplicate node(s) (same paper across OpenAlex/arXiv)")
    log(f"Network: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
    fixed = clean_years(graph)
    if fixed:
        log(f"Cleaned {fixed} dirty publication year(s) via citation-order check")
    log("Computing graph metrics ...")
    compute_metrics(graph)

    from .relevance import prune_off_topic, tag_relevance

    log("Tagging topic relevance (core/related/off-topic) ...")
    rc = tag_relevance(graph, nq, llm)
    log(f"relevance: {rc}")
    if s.prune_off_topic:
        n_pruned = prune_off_topic(graph)
        if n_pruned:
            log(f"Pruned {n_pruned} off-topic nodes; recomputing metrics on clean graph")
            compute_metrics(graph)

    log("Locating founding paper(s) ...")
    founding = find_founding(graph, llm, nq)

    log("Filtering key papers & building roadmap ...")
    roadmap = select_key_papers(graph, llm, nq, founding=founding)

    log("Synthesizing analysis report ...")
    seed_id = seeds[0].id if seeds else None
    report = analyze(graph, roadmap, founding, llm, nq, seed_id=seed_id)

    result = PipelineResult(
        query=nq,
        seeds=[p.id for p in seeds],
        graph=graph,
        founding=founding,
        roadmap=roadmap,
        report=report,
        llm_used=llm.available,
    )

    # Best-effort localization (skippable via translate=False to speed up eval).
    if s.translate:
        try:
            from .translate import localize

            log("Localizing report (zh) ...")
            localize(result, llm, "zh")
        except Exception:
            pass

    cache.close()
    return result
