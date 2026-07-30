"""Agentic orchestration combining the five patterns into one flow."""
from __future__ import annotations

from ..config import Settings
from ..llm.base import LLMClient
from ..models import PipelineResult
from ..sources.base import DataSource
from ..core.analyzer import analyze
from ..core.collector import build_graph
from ..core.filter import select_key_papers
from ..core.founding import _foundational_scores, find_founding
from ..core.graph import clean_years, compute_metrics, dedupe_nodes
from ..core.resolver import resolve
from .runtime import Agent
from .tools import scout_tools
from .verify import verify_claim
from .workspace import Workspace

SCOUT_SYS = (
    "You are a research scout building a citation network for a field. You decide, step by "
    "step, which papers to expand and in which direction, using the running graph summary. "
    "Prefer expanding high-citation, not-yet-expanded nodes. Expand backward to find origins "
    "and forward to see development. Finish once coverage looks representative."
)


async def run_agentic(
    query: str,
    source: DataSource,
    llm: LLMClient,
    settings: Settings,
    progress=None,
    on_event=None,
) -> PipelineResult:
    def log(m: str):
        if progress:
            progress(m)

    ws = Workspace(query, settings, on_event=on_event)

    # ---- resolve seeds (dual-source OpenAlex + arXiv, relevance-gated) ---
    from ..sources.arxiv import ArxivSource

    arxiv = ArxivSource()
    try:
        nq, seeds = await resolve(
            query, source, llm, n_seeds=1, arxiv=arxiv, on_event=on_event
        )
    finally:
        await arxiv.aclose()
    if not seeds:
        raise RuntimeError(f"No papers found for query: {query!r}")
    ws.query = nq
    for p in seeds:
        ws.add_seed(p)
    ws.trace.add("orchestrator", "note", f"seeds: {[p.title[:50] for p in seeds]}")

    # ---- 0) survey-first: seed graph with LLM-curated survey papers ------
    if settings.use_surveys and llm.available:
        log("Survey-first: mining recent surveys & curating references ...")
        from ..core.surveys import curate_survey_papers

        survey_papers = await curate_survey_papers(nq, source, llm, settings)
        added = sum(ws.add_paper(p, 1) for p in survey_papers)
        ws.trace.add("orchestrator", "note", f"survey-curated {added} field papers added")

    # ---- 1) graph-guided scouting (tool-using ReAct agent) --------------
    if llm.available:
        steps = max(4, min(12, settings.max_nodes // 15))
        log(f"ScoutAgent exploring (≤{steps} steps, graph-guided) ...")
        scout = Agent(
            "scout", SCOUT_SYS, llm, tools=scout_tools(ws, source), trace=ws.trace, max_steps=steps
        )
        await scout.run(
            f"Build a representative citation network for: '{nq}'. "
            f"Seeds already in the graph. Aim for ~{min(settings.max_nodes, 80)} key papers, "
            f"then finish.\n\n{ws.summary()}"
        )

    # safety net: ensure a non-trivial graph even if the agent under-explored
    if len(ws.papers) < 10:
        log("Scout under-explored; running deterministic expansion as backstop ...")
        graph = await build_graph(seeds, source, settings, query=nq)
    else:
        graph = ws.to_graph()

    dups = dedupe_nodes(graph)
    if dups:
        log(f"Entity alignment: merged {dups} duplicate node(s) (same paper across OpenAlex/arXiv)")
    log(f"Network: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
    fixed = clean_years(graph)
    if fixed:
        log(f"Self-correction: fixed {fixed} dirty year(s) via citation-order check")
    compute_metrics(graph)

    from ..core.relevance import prune_off_topic, tag_relevance

    rc = tag_relevance(graph, nq, llm)
    ws.trace.add("orchestrator", "note", {"relevance": rc})
    if settings.prune_off_topic:
        n_pruned = prune_off_topic(graph)
        if n_pruned:
            ws.trace.add("orchestrator", "note", f"pruned {n_pruned} off-topic nodes")
            compute_metrics(graph)

    # ---- 2) founding + adversarial verification + self-correction -------
    log("FoundingAgent proposing + adversarial verification ...")
    founding = find_founding(graph, llm, nq)
    verified, refuted = await _verify_founding(graph, llm, nq, founding, ws)

    if not verified and llm.available:
        ws.trace.add("orchestrator", "self_correct", "all founding candidates refuted; re-picking")
        scores = _foundational_scores(graph)
        ranked = sorted(
            (n for n in graph.nodes if n.paper_id not in refuted),
            key=lambda n: scores[n.paper_id],
            reverse=True,
        )
        for n in ranked[:3]:
            v, _r = await _verify_founding(graph, llm, nq, [n.paper_id], ws)
            if v:
                verified = v
                break

    # fallback when verification confirms nothing: prefer the seed (user's anchor),
    # never a refuted tangential old paper from a skewed candidate pool
    node_ids = {n.paper_id for n in graph.nodes}
    seed_fallback = [s for s in graph.seeds if s in node_ids][:1]
    final_founding = verified or seed_fallback or founding[:1]
    if not verified:
        ws.trace.add("orchestrator", "self_correct",
                     f"no candidate verified -> fallback to {'seed' if seed_fallback else 'top graph pick'}")
    _retag_founding(graph, final_founding)
    ws.trace.add("orchestrator", "note", {"final_founding": final_founding})

    # ---- 3) curator: key papers + roadmap (reuses graph-pre-ranked LLM) -
    log("CuratorAgent selecting key papers & roadmap ...")
    roadmap = select_key_papers(graph, llm, nq, founding=final_founding)

    # ---- 4) synthesizer + consistency self-check -----------------------
    log("SynthesizerAgent writing report ...")
    seed_id = seeds[0].id if seeds else None
    report = analyze(graph, roadmap, final_founding, llm, nq, seed_id=seed_id)
    _consistency_check(roadmap, final_founding, ws)

    result = PipelineResult(
        query=nq,
        seeds=[p.id for p in seeds],
        graph=graph,
        founding=final_founding,
        roadmap=roadmap,
        report=report,
        llm_used=llm.available,
        agentic=True,
        trace=ws.trace.dump(),
    )

    if settings.translate:
        try:
            from ..core.translate import localize

            log("Localizing report (zh) ...")
            localize(result, llm, "zh")
        except Exception:
            pass

    return result


async def _verify_founding(graph, llm, query, ids, ws):
    verified, refuted = [], set()
    indeg = {n.paper_id: n.metrics.get("in_degree", 0) for n in graph.nodes}
    for fid in ids:
        p = graph.papers.get(fid)
        if not p:
            continue
        claim = (
            f"'{p.title}' ({p.year}) is a foundational/seminal work for the research field centered "
            f"on '{query}' — i.e. it introduced, or is a direct progenitor of, the field's core ideas."
        )
        ctx = (
            f"global citations={p.citation_count}; cited by {indeg.get(fid,0)} papers in this network; "
            f"abstract: {(p.abstract or '')[:300]}"
        )
        res = await verify_claim(llm, claim, ctx, n=3, trace=ws.trace)
        if res["verdict"]:
            verified.append(fid)
        else:
            refuted.add(fid)
    return verified, refuted


def _retag_founding(graph, founding_ids):
    fset = set(founding_ids)
    for n in graph.nodes:
        if n.role == "founding" and n.paper_id not in fset:
            n.role = None
    for n in graph.nodes:
        if n.paper_id in fset:
            n.role = "founding"


def _consistency_check(roadmap, founding, ws):
    issues = []
    yrs = [n.year for n in roadmap.nodes if n.year]
    if yrs and yrs != sorted(yrs):
        issues.append("roadmap not strictly chronological")
    rm_ids = {n.paper_id for n in roadmap.nodes}
    missing = [f for f in founding if f not in rm_ids]
    if missing:
        issues.append(f"{len(missing)} founding paper(s) missing from roadmap")
    ws.trace.add("orchestrator", "consistency", issues or "ok")
