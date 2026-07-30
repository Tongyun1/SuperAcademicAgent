"""Graph-building tools: resolve seeds, search, expand, inspect.

Thin Stirrup wrappers over the superacademic engine + a shared Workspace. Mirrors
the logic of superacademic.agents.tools.scout_tools, but as typed Stirrup Tools so
the agent-loop drives exploration and decides when it has enough.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from stirrup import Tool, ToolResult, ToolUseCountMetadata
from stirrup.core.models import EmptyParams

from ..context import RunContext


def _ok(content: str) -> ToolResult[ToolUseCountMetadata]:
    return ToolResult(content=content, metadata=ToolUseCountMetadata(), success=True)


class SearchParams(BaseModel):
    query: str = Field(description="Free-text search string to find more papers in this field.")


class RecentSearchParams(BaseModel):
    query: str = Field(
        description="Free-text search string. Use a SHORT tight phrase — a specific named "
        "sub-technique/acronym when you're chasing a hot narrow wave, or the general topic otherwise."
    )
    sort: str = Field(
        default="submittedDate",
        description="arXiv sort order: 'submittedDate' surfaces the newest follow-ups (best for "
        "catching this week's/month's papers); 'relevance' surfaces the paper most central to the "
        "phrase, which may be slightly older (often the one that started a sub-wave). If a narrow "
        "phrase matters, call search_recent twice — once with each sort — to get both angles.",
    )


class ExpandParams(BaseModel):
    paper_id: str = Field(description="A paper id shown in the graph summary (e.g. 'W2626778328').")


def build_graph_tools(ctx: RunContext) -> list[Tool]:
    ws = ctx.ws
    s = ctx.settings
    frontier_done: set[str] = set()  # paper_ids already frontier-expanded this run

    async def graph_search(p: SearchParams) -> ToolResult[ToolUseCountMetadata]:
        hits = await ctx.source.search(p.query, limit=8)
        added = sum(ws.add_paper(h, 1) for h in hits)
        return _ok(f"search('{p.query}'): {len(hits)} hits, {added} new added.\n" + ws.summary())

    async def expand_forward(p: ExpandParams) -> ToolResult[ToolUseCountMetadata]:
        pid = p.paper_id
        if pid not in ws.papers:
            return _ok(f"'{pid}' not in graph. Pick a paper_id shown in the summary.")
        if pid in ws.expanded_fwd:
            return _ok(f"'{pid}' already expanded forward.")
        depth = ws.depth.get(pid, 0) + 1
        # most-cited citing papers (established descendants)
        citing = await ctx.source.get_citing(pid, s.per_node_citations, "citations")
        added = sum(ws.add_paper(c, depth) for c in citing)
        # ALSO the recent frontier: newest papers rank ~0 by raw citations, so the
        # most-cited sort systematically misses 2022+ work — pull it explicitly.
        recent = []
        if s.per_node_recent > 0:
            recent = await ctx.source.get_citing(pid, s.per_node_recent, "recent_cited")
            added += sum(ws.add_paper(c, depth) for c in recent)
        ws.expanded_fwd.add(pid)
        return _ok(
            f"expand_forward({pid}): {len(citing)} most-cited + {len(recent)} recent citing papers, "
            f"{added} new added.\n" + ws.summary()
        )

    async def expand_frontier(p: ExpandParams) -> ToolResult[ToolUseCountMetadata]:
        pid = p.paper_id
        if pid not in ws.papers:
            return _ok(f"'{pid}' not in graph. Pick a paper_id shown in the summary.")
        if pid in frontier_done:
            return _ok(f"'{pid}' already frontier-expanded.")
        depth = ws.depth.get(pid, 0) + 1
        # IMPORTANT frontier first: recent papers ranked by citations (recent_cited) —
        # this is where Mamba/RWKV-tier new architectures live. Pure newest-by-date
        # ("recent") is dominated by ~0-citation drive-by application papers (noise), so
        # we take only a small bleeding-edge slice of it.
        important = await ctx.source.get_citing(pid, max(s.per_node_recent, 15), "recent_cited")
        added = sum(ws.add_paper(c, depth) for c in important)
        newest = await ctx.source.get_citing(pid, 5, "recent")
        added += sum(ws.add_paper(c, depth) for c in newest)
        frontier_done.add(pid)
        got = important + newest
        years = sorted({c.year for c in got if c.year}, reverse=True)[:5]
        return _ok(
            f"expand_frontier({pid}): {len(important)} important-recent + {len(newest)} newest "
            f"citing papers (years: {years}), {added} new added.\n" + ws.summary()
        )

    async def expand_backward(p: ExpandParams) -> ToolResult[ToolUseCountMetadata]:
        pid = p.paper_id
        if pid not in ws.papers:
            return _ok(f"'{pid}' not in graph.")
        if pid in ws.expanded_bwd:
            return _ok(f"'{pid}' already expanded backward.")
        refs = ws.papers[pid].referenced_works[: s.per_node_references]
        papers = await ctx.source.get_many(refs) if refs else []
        added = sum(ws.add_paper(pp, ws.depth.get(pid, 0) + 1) for pp in papers)
        ws.expanded_bwd.add(pid)
        return _ok(f"expand_backward({pid}): {len(refs)} references, {added} new added.\n" + ws.summary())

    async def search_recent(p: RecentSearchParams) -> ToolResult[ToolUseCountMetadata]:
        # newest papers on the topic, by DATE (or by relevance if requested) — reaches
        # brand-new follow-ups that have ~0 citations and unindexed citation edges
        # (missed by graph_search/expansion). OpenAlex indexing lags arXiv by months, so
        # for a hot sub-topic that just took off it can return literally 0 — arXiv is
        # the primary source here, OpenAlex is a bonus when it has caught up. `sort` is
        # the agent's call: pick submittedDate for the newest wave, relevance to find
        # what's most central to the phrase (which may be slightly older).
        oa = await ctx.source.search_recent(p.query, limit=15)
        ax = await ctx.arxiv.search(p.query, max_results=15, sort=p.sort) if ctx.arxiv else []
        hits = oa + ax
        added = sum(ws.add_paper(h, 1) for h in hits)
        yrs = sorted({h.year for h in hits if h.year}, reverse=True)[:4]
        return _ok(
            f"search_recent('{p.query}', sort={p.sort}): {len(hits)} recent papers "
            f"(years: {yrs}), {added} new added — use this to catch the latest follow-ups.\n" + ws.summary()
        )

    async def mine_surveys(_p: EmptyParams) -> ToolResult[ToolUseCountMetadata]:
        from saagent.engine.core.surveys import curate_survey_papers

        papers = await curate_survey_papers(ws.query, ctx.source, ctx.llm, ctx.settings)
        if not papers:
            return _ok("mine_surveys: no recent surveys found (or LLM unavailable). Try graph_search instead.")
        added = sum(ws.add_paper(pp, 1) for pp in papers)
        ws.trace.add("agent", "surveys", f"{len(papers)} survey+curated refs, {added} new")
        return _ok(
            f"mine_surveys: mined recent surveys + their expert-curated key references — "
            f"{len(papers)} papers, {added} new added. This is a high-signal way to reach the "
            f"field's important recent work (what survey authors deem worth citing).\n" + ws.summary()
        )

    async def graph_summary(_p: EmptyParams) -> ToolResult[ToolUseCountMetadata]:
        return _ok(ws.summary())

    return [
        Tool[SearchParams, ToolUseCountMetadata](
            name="graph_search",
            description="Free-text search for more papers in this field and add hits to the graph.",
            parameters=SearchParams,
            executor=graph_search,
        ),
        Tool[RecentSearchParams, ToolUseCountMetadata](
            name="search_recent",
            description="Find recent papers on a topic (OpenAlex + arXiv). Use this to catch brand-new follow-up / frontier papers that have ~0 citations and unindexed citation edges — they won't show up via graph_search (relevance-ranked) or citation expansion. Pass a tight topic phrase. Choose `sort`: 'submittedDate' for the newest by-date wave, 'relevance' for what's most central to the phrase — call it twice with both sorts when a narrow hot phrase matters.",
            parameters=RecentSearchParams,
            executor=search_recent,
        ),
        Tool[ExpandParams, ToolUseCountMetadata](
            name="expand_forward",
            description="Fetch papers that CITE a node (newer work): both the most-cited descendants AND the recent frontier. Use on key nodes to see how the field developed.",
            parameters=ExpandParams,
            executor=expand_forward,
        ),
        Tool[ExpandParams, ToolUseCountMetadata](
            name="expand_frontier",
            description="Fetch the NEWEST papers citing a node (this year / last year), even if they have ~0 citations yet. Use on the founding/central node to reach the bleeding edge (2024-2026) that citation-ranked expansion misses.",
            parameters=ExpandParams,
            executor=expand_frontier,
        ),
        Tool[ExpandParams, ToolUseCountMetadata](
            name="expand_backward",
            description="Fetch a node's REFERENCES (older work) to trace where its ideas came from.",
            parameters=ExpandParams,
            executor=expand_backward,
        ),
        Tool[EmptyParams, ToolUseCountMetadata](
            name="mine_surveys",
            description="Find recent SURVEYS of the field and pull their expert-curated key references. High-signal way to reach the important recent work (incl. landmark architectures) that citation expansion can miss when a seed's citation data is sparse/broken. Use it while building the graph.",
            parameters=EmptyParams,
            executor=mine_surveys,
        ),
        Tool[EmptyParams, ToolUseCountMetadata](
            name="graph_summary",
            description="Show the current citation graph: node count and top papers by citations.",
            parameters=EmptyParams,
            executor=graph_summary,
        ),
    ]
