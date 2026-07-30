"""Seed selection tools — the autonomous replacement for resolve_seeds.

Instead of a black box that recalls candidates AND picks the seed for the model,
we split it: `find_candidates` only recalls (dual-source, no LLM gate) and returns
the raw list; the agent inspects, asks the user when the candidates span different
fields, then commits its choice with `add_seed`. This gives the model full control
over disambiguation (and naturally triggers ask_user on genuine ambiguity).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from stirrup import Tool, ToolResult, ToolUseCountMetadata
from saagent.engine.core.resolver import _looks_like_id
from saagent.engine.models import Paper
from saagent.engine.util.text import normalize_title

from ..context import RunContext


def _ok(content: str) -> ToolResult[ToolUseCountMetadata]:
    return ToolResult(content=content, metadata=ToolUseCountMetadata(), success=True)


class FindCandidatesParams(BaseModel):
    query: str = Field(
        default="",
        description="Term / paper title / fuzzy description / identifier to look up. Empty = use the run's original query.",
    )


class AddSeedParams(BaseModel):
    paper_id: str = Field(description="id of a candidate (from find_candidates) to commit as a seed/anchor of the graph.")
    match_rationale: str = Field(
        description="Required self-check before committing: state the paper's actual technique/"
        "contribution (what it specifically does), then compare that against the exact wording "
        "of the current research topic — not just whether they share vocabulary. If the "
        "comparison reveals the paper is actually a different technique/field than the topic "
        "asks about, do not add_seed it — ask_user instead.",
    )
    set_topic: str = Field(
        default="",
        description="Optional: only pass this if the ORIGINAL query was too vague to search/frame "
        "with (e.g. an ambiguous acronym) and this seed resolves what the field actually is — then "
        "give a short topic phrase in your own words (NOT necessarily the seed's raw title, which "
        "may be too broad, e.g. a survey title) to anchor downstream relevance/founding/report on. "
        "Leave empty to keep the user's original query as the anchor — this is the common case.",
    )


def _fmt(p: Paper) -> str:
    srcs = []
    if p.id.startswith("W") or (p.source_ids or {}).get("openalex"):
        srcs.append("openalex")
    if (p.source_ids or {}).get("arxiv"):
        srcs.append("arXiv")
    src = "+".join(srcs) or "openalex"
    venue = f" | {p.venue}" if p.venue else ""
    return f"  {p.id} | {p.year} | cites={p.citation_count} | {src}{venue} | {p.title[:80]}"


def _reconcile(a: Paper, b: Paper) -> Paper:
    """Merge two same-title records (cross-source) into one clean candidate.

    Why: the same paper often appears as both an OpenAlex work and an arXiv
    preprint, and OpenAlex records can carry a wrong (re-indexed) year — e.g.
    "Attention Is All You Need" comes back as 2025 from OpenAlex while arXiv
    (1706.03762) correctly says 2017. Dropping either record (the old behaviour)
    hid the correct signal from the model. Instead we keep ONE candidate and
    reconcile: prefer the OpenAlex id as primary (it carries citation edges for
    graph expansion), take the EARLIEST plausible year (a paper's canonical year
    is its first appearance), union the source ids (so the arXiv id rides along
    for later full-text link-back), and keep the richest of the other fields.
    """
    primary, other = (a, b) if a.id.startswith("W") else ((b, a) if b.id.startswith("W") else (a, b))
    sources = {**(other.source_ids or {}), **(primary.source_ids or {})}
    for m in (a, b):  # make sure an arXiv id from either member is captured
        if m.id.startswith("arxiv:"):
            sources.setdefault("arxiv", m.id.split(":", 1)[1])
    years = [y for y in (a.year, b.year) if y and y > 1500]
    return primary.model_copy(update={
        "year": min(years) if years else primary.year,
        "citation_count": max(a.citation_count or 0, b.citation_count or 0),
        "source_ids": sources,
        "arxiv_url": primary.arxiv_url or other.arxiv_url,
        "pdf_url": primary.pdf_url or other.pdf_url,
        "doi": primary.doi or other.doi,
        "abstract": primary.abstract or other.abstract,
        "venue": primary.venue or other.venue,
    })


def build_seed_tools(ctx: RunContext) -> list[Tool]:
    candidates: dict[str, Paper] = {}  # shared cache: id -> Paper, populated by find_candidates

    async def find_candidates(p: FindCandidatesParams) -> ToolResult[ToolUseCountMetadata]:
        ctx.set_research_mode(True)
        q = (p.query or ctx.ws.query).strip()
        groups: dict[str, Paper] = {}  # normalized title -> merged Paper (dict preserves insertion order)

        def _add(papers):
            for pp in papers:
                key = normalize_title(pp.title)
                if not pp.id or not key:
                    continue
                # merge same-title records across sources instead of dropping duplicates
                groups[key] = _reconcile(groups[key], pp) if key in groups else pp

        if _looks_like_id(q):
            paper = await ctx.source.get_paper(q)
            if paper:
                _add([paper])
        if not groups:
            _add(await ctx.source.search(q, limit=8))
            # search() is plain relevance search, not date-aware — a paper published
            # days/weeks ago may not rank in its top hits (or isn't indexed yet at all).
            # search_recent() date-filters+sorts, mirroring the arXiv submittedDate call
            # below, so a brand-new OpenAlex-side record doesn't get silently missed.
            _add(await ctx.source.search_recent(q, limit=4))
            _add(await ctx.arxiv.search(f'"{q}"', max_results=6, sort="relevance"))
            _add(await ctx.arxiv.search(q, max_results=4, sort="submittedDate"))

        found = list(groups.values())
        for pp in found:
            candidates[pp.id] = pp

        if not found:
            return _ok(
                f"find_candidates('{q}'): no papers found. The term may be misspelled or too obscure — "
                f"consider asking the user for the full title, authors, or field."
            )
        lines = [
            f"find_candidates('{q}'): {len(found)} candidate(s) (same-title records merged across OpenAlex+arXiv; "
            f"year = earliest appearance). List order is just call order (OpenAlex then arXiv), NOT a "
            f"relevance ranking — judge each by its year/cites, don't assume an earlier position means a "
            f"better match. A candidate with a recent year and near-zero citations may be a brand-new paper "
            f"that isn't well-indexed yet; if the query looks like it's pointing at a specific recent paper, "
            f"don't discount such a candidate just because it's outranked on citations or listed later. If "
            f"candidates span different fields/topics, ask the user which to focus on (offer them as choices), "
            f"then add_seed the chosen one. For a well-known paper prefer the candidate whose title exactly "
            f"matches and that appears on both sources. If they clearly agree on one topic, add_seed the best "
            f"match."
        ]
        lines += [_fmt(pp) for pp in found]
        return _ok("\n".join(lines))

    async def add_seed(p: AddSeedParams) -> ToolResult[ToolUseCountMetadata]:
        ctx.set_research_mode(True)
        pid = p.paper_id
        paper = candidates.get(pid) or ctx.ws.papers.get(pid)
        if paper is None:
            paper = await ctx.source.get_paper(pid)
        if paper is None:
            return _ok(f"'{pid}' not found. Pick a paper_id from find_candidates output.")
        # topic anchor is the user's original query by default; only change it if the
        # agent explicitly asks to (set_topic) — never silently overwritten with the
        # seed's raw title, which can be too broad (e.g. a survey) or off-focus.
        if p.set_topic.strip():
            ctx.ws.query = p.set_topic.strip()
        ctx.ws.add_seed(paper)
        ctx.ws.trace.add("agent", "seed", f"{paper.id} | {paper.title[:60]} | rationale: {p.match_rationale[:200]}")
        return _ok(
            f"add_seed: '{paper.title[:70]}' ({paper.year}) anchored as seed. Topic now = '{ctx.ws.query[:60]}'.\n"
            + ctx.ws.summary()
        )

    return [
        Tool[FindCandidatesParams, ToolUseCountMetadata](
            name="find_candidates",
            description="Recall candidate papers for a term from OpenAlex + arXiv (no auto-pick). Returns titles/years/citations/venue so YOU can judge which topic the user means. First step; inspect before committing a seed.",
            parameters=FindCandidatesParams,
            executor=find_candidates,
        ),
        Tool[AddSeedParams, ToolUseCountMetadata](
            name="add_seed",
            description="Commit a candidate (by paper_id from find_candidates) as a seed/anchor of the citation graph. Requires match_rationale: a genuine self-check of the paper's actual technique against the topic's exact wording, not a rubber stamp. The topic anchor used for relevance/founding/report stays the user's original query unless you pass `set_topic`. Add 1-3 seeds, then expand.",
            parameters=AddSeedParams,
            executor=add_seed,
        ),
    ]
