"""Step C1: normalize input into seed papers — robust, relevance-gated, dual-source.

Lesson from a failed attempt: a brittle "frontier vs established" classification +
query broadening produced garbage seeds (an economics paper for "on-policy distillation").
Fix: keep the user's EXACT query (no broadening), gather candidates from BOTH OpenAlex
(citation DB) and arXiv (newest), then have the LLM pick the on-topic seed(s) from the
real candidate list — with a term-overlap fallback. Selection over concrete papers is far
more reliable than abstract maturity classification.
"""
from __future__ import annotations

import re

from ..llm.base import LLMClient
from ..llm.prompts import select_seeds
from ..models import Paper
from ..sources.base import DataSource
from ..util.text import normalize_title

_ID_PATTERNS = [
    re.compile(r"^[Ww]\d+$"),  # OpenAlex
    re.compile(r"^10\.\d{4,9}/"),  # DOI
    re.compile(r"doi\.org/", re.I),
    re.compile(r"arxiv", re.I),
    re.compile(r"openalex\.org/", re.I),
]

_STOP = {"the", "a", "an", "of", "for", "and", "on", "in", "to", "with", "via", "using"}


def _looks_like_id(text: str) -> bool:
    t = text.strip()
    if " " in t and not any(p.search(t) for p in _ID_PATTERNS[2:]):
        return False
    return any(p.search(t) for p in _ID_PATTERNS)


def _overlap(query: str, title: str) -> int:
    q = {w for w in normalize_title(query).split() if w not in _STOP}
    t = set(normalize_title(title).split())
    return len(q & t)


async def resolve(
    query: str,
    source: DataSource,
    llm: LLMClient,
    *,
    n_seeds: int = 1,
    arxiv=None,
    on_event=None,
) -> tuple[str, list[Paper]]:
    """Return (query, seed_papers)."""
    q = query.strip()

    # 1) explicit identifier (DOI / arXiv / OpenAlex id / URL)
    if _looks_like_id(q):
        paper = await source.get_paper(q)
        if paper:
            return paper.title, [paper]

    # 2) gather candidates from BOTH sources, using the EXACT query (no broadening)
    candidates: list[Paper] = []
    seen: set[str] = set()

    def _add(papers):
        for p in papers:
            key = normalize_title(p.title)
            if p.id and key and key not in seen:
                seen.add(key)
                candidates.append(p)

    _add(await source.search(q, limit=8))
    if arxiv is not None:
        _add(await arxiv.search(f'"{q}"', max_results=6, sort="relevance"))
        _add(await arxiv.search(q, max_results=4, sort="submittedDate"))

    if not candidates:
        return q, []

    # 3) LLM picks the on-topic seed(s) from real candidates (relevance gate)
    seeds: list[Paper] = []
    if llm.available and len(candidates) > 1:
        payload = [
            {
                "idx": i,
                "title": p.title,
                "year": p.year,
                "citation_count": p.citation_count,
                "source": "arXiv" if p.source_ids.get("arxiv") else "openalex",
            }
            for i, p in enumerate(candidates)
        ]
        out = llm.complete_json(*select_seeds(q, payload))
        if isinstance(out, dict):
            chosen = [c for c in (out.get("chosen") or []) if isinstance(c, int) and 0 <= c < len(candidates)]
            seeds = [candidates[i] for i in chosen][: max(n_seeds, 3)]
            if on_event:
                on_event({"i": -1, "agent": "resolver", "type": "note",
                          "content": f"seeds: {[s.title[:40] for s in seeds]} — {str(out.get('reason',''))[:80]}"})

    # 4) fallback: best term-overlap with the query
    if not seeds:
        ranked = sorted(candidates, key=lambda p: (_overlap(q, p.title), p.citation_count), reverse=True)
        seeds = ranked[: max(n_seeds, 1)]

    return q, seeds