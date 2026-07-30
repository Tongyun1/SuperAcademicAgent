"""Analysis tools: founding, roadmap, report — thin wrappers over the superacademic engine.

These operate on a materialized CitationGraph (with metrics + relevance tags), built
once from the shared Workspace by `_ensure_graph` and cached on the RunContext.
"""

from __future__ import annotations

from stirrup import Tool, ToolResult, ToolUseCountMetadata
from stirrup.core.models import EmptyParams
from saagent.engine.core.analyzer import analyze
from saagent.engine.core.filter import select_key_papers
from saagent.engine.core.founding import find_founding
from saagent.engine.core.graph import clean_years, compute_metrics, dedupe_nodes
from saagent.engine.core.relevance import prune_noise, prune_off_topic, tag_relevance
from saagent.engine.models import CitationGraph

from ..context import RunContext


def _ok(content: str) -> ToolResult[ToolUseCountMetadata]:
    return ToolResult(content=content, metadata=ToolUseCountMetadata(), success=True)


def _ensure_graph(ctx: RunContext) -> CitationGraph:
    """Materialize the citation graph from the workspace, once, ready for analysis.

    Runs the deterministic prep the engine expects before founding/roadmap/report:
    to_graph -> entity dedup -> year self-heal -> metrics (PageRank/velocity/…) ->
    topic-relevance tagging -> optional off-topic prune. Cached on ctx.graph.
    """
    if ctx.graph is not None:
        return ctx.graph
    g = ctx.ws.to_graph()
    dedupe_nodes(g)
    clean_years(g)
    # correct citation counts (OpenAlex can be wrong, e.g. Attention=6576 vs ~182k)
    # via Semantic Scholar BEFORE metrics so PageRank/velocity/founding use good numbers
    try:
        from saagent.engine.sources.semanticscholar import enrich_citations
        enrich_citations(g, ctx.settings, getattr(ctx, "cache", None), trace=ctx.ws.trace)
    except Exception as e:  # noqa: BLE001 — enrichment is best-effort
        ctx.ws.trace.add("agent", "note", f"S2 enrichment skipped: {e}")
    compute_metrics(g)
    try:
        # Anchor relevance on the topic PLUS the committed seeds' titles: seeds are the user's
        # confirmed research target, so even if ctx.ws.query is weak/wrong (e.g. a chat opener
        # like "你好") the seed titles keep tagging on-topic. Belt to the tui-side anchor fix.
        title_by_id = {n.paper_id: n.title for n in g.nodes if n.title}
        seed_titles = [title_by_id[s] for s in (g.seeds or []) if s in title_by_id]
        anchor = ctx.ws.query
        if seed_titles:
            anchor = f"{ctx.ws.query} — seed papers defining the topic: " + "; ".join(seed_titles[:5])
        tag_relevance(g, anchor, ctx.llm)
        if ctx.settings.prune_off_topic:
            total = len(g.nodes)
            seedset = set(g.seeds or [])
            off = sum(
                1 for n in g.nodes
                if n.metrics.get("relevance") == "off-topic" and n.paper_id not in seedset
            )
            # Safety valve: near-total off-topic means the anchor is almost certainly wrong
            # (or tagging misfired) — pruning would collapse the graph to just its seeds
            # (the exact "3-node network" failure). Skip the prune and warn instead.
            if total >= 8 and off >= 0.8 * total:
                ctx.ws.trace.add(
                    "agent", "note",
                    f"⚠ off-topic prune skipped: {off}/{total} nodes tagged off-topic — "
                    f"topic anchor likely wrong; kept the graph intact",
                )
            else:
                prune_off_topic(g)
                # de-noise: drop 0-citation drive-by leaves (tangential apps that merely cite
                # a classic). Protects seeds/founding; connected frontier (link_frontier) survives.
                removed = prune_noise(g, protect=set(ctx.founding or []))
                if removed:
                    ctx.ws.trace.add("agent", "note", f"de-noise: dropped {removed} peripheral 0-cite leaf paper(s)")
                compute_metrics(g)  # recompute after pruning
    except Exception as e:  # noqa: BLE001 — relevance is best-effort
        ctx.ws.trace.add("agent", "note", f"relevance tagging skipped: {e}")
    ctx.graph = g
    return g


def build_analysis_tools(ctx: RunContext) -> list[Tool]:
    def find_founding_tool(_p: EmptyParams) -> ToolResult[ToolUseCountMetadata]:
        g = _ensure_graph(ctx)
        founding = find_founding(g, ctx.llm, ctx.ws.query)
        ctx.founding = list(founding)
        fset = set(founding)
        for n in g.nodes:
            if n.paper_id in fset:
                n.role = "founding"
        ctx.ws.trace.add("agent", "founding", ctx.founding)
        lines = [f"find_founding: {len(founding)} founding paper(s)."]
        for pid in founding:
            n = g.node(pid)
            if n:
                lines.append(f"  {pid} | {n.year} | cites={n.citation_count} | {n.title[:70]}")
        lines.append(
            "Before proceeding, check each title against the exact wording/technique of the "
            "research topic — a title can look like a match while actually referring to a "
            "different technique or field. If any founding paper's fit is not clearly certain, "
            "ask_user to confirm before moving on to select_roadmap."
        )
        return _ok("\n".join(lines))

    def select_roadmap_tool(_p: EmptyParams) -> ToolResult[ToolUseCountMetadata]:
        g = _ensure_graph(ctx)
        ctx.roadmap = select_key_papers(g, ctx.llm, ctx.ws.query, founding=ctx.founding)
        n_nodes = len(ctx.roadmap.nodes)
        ctx.ws.trace.add("agent", "roadmap", f"{n_nodes} key papers")
        lines = [f"select_roadmap: {n_nodes} key papers on the evolution roadmap."]
        for rn in ctx.roadmap.nodes[:12]:
            lines.append(f"  {rn.year} | {rn.role} | {rn.title[:60]}")
        return _ok("\n".join(lines))

    def write_report_tool(_p: EmptyParams) -> ToolResult[ToolUseCountMetadata]:
        g = _ensure_graph(ctx)
        seed_id = ctx.ws.seeds[0] if ctx.ws.seeds else None
        ctx.report = analyze(g, ctx.roadmap, ctx.founding, ctx.llm, ctx.ws.query, seed_id=seed_id)
        rep = ctx.report
        ctx.ws.trace.add("agent", "report", "field report written" + (" (degraded)" if rep.degraded else ""))
        bits = [
            f"write_report: report generated.",
            f"  stages: {len(rep.stages)} · must_read: {len(rep.must_read)} · gaps: {len(rep.gaps)}",
        ]
        if rep.degraded:
            bits.append(
                "  ⚠ WARNING: LLM failed to generate the full report (JSON parse error or timeout). "
                "The report is a heuristic fallback — it lacks tldr, cover_title, cover_blurb, "
                "glossary, and getting_started. Ask the user whether to retry or skip: call ask_user with "
                "question_type='choice' and choices=['Retry write_report (recommended)', "
                "'Skip and continue with reduced report']. If ask_user is unavailable (--no-ask mode), "
                "retry write_report once automatically. If it fails again, proceed with the reduced report."
            )
        elif rep.tldr:
            bits.append(f"  tldr: {rep.tldr[:160]}")
        return _ok("\n".join(bits))

    return [
        Tool[EmptyParams, ToolUseCountMetadata](
            name="find_founding",
            description="Identify the field's foundational paper(s): graph pre-ranking (PageRank/citations, topic-core only) + LLM review. Sets founding roles. Call after the graph is built.",
            parameters=EmptyParams,
            executor=find_founding_tool,
        ),
        Tool[EmptyParams, ToolUseCountMetadata](
            name="select_roadmap",
            description="Select the key evolution papers and build the roadmap DAG (roles: founding/breakthrough/improvement/branch/survey + evolution edges). Call after find_founding.",
            parameters=EmptyParams,
            executor=select_roadmap_tool,
        ),
        Tool[EmptyParams, ToolUseCountMetadata](
            name="write_report",
            description="Write the beginner-facing field report (tldr / core idea / prerequisites / glossary / getting-started + stages / must-read / gaps). Call after select_roadmap.",
            parameters=EmptyParams,
            executor=write_report_tool,
        ),
    ]
