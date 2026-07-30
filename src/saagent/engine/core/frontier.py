"""Connect frontier papers (recent, citation-disconnected) to the lineage via full text.

A brand-new paper has ~0 incoming citations AND its outgoing references aren't indexed
yet (OpenAlex/S2 lag, arXiv gives none). So it floats disconnected. Fix: read its PDF,
let the LLM extract the prior works it builds on, resolve those to real papers, and wire
them in as references — the connection comes from the TEXT, not the citation graph.
"""
from __future__ import annotations

import asyncio

from ..llm.base import LLMClient
from ..llm.prompts import extract_lineage
from ..models import Paper
from ..util.text import normalize_title


def _overlap(a: str, b: str) -> int:
    sa = {w for w in normalize_title(a).split() if len(w) > 3}
    sb = set(normalize_title(b).split())
    return len(sa & sb)


async def _link_one(p: Paper, source, arxiv, llm: LLMClient, on_event) -> dict[str, Paper]:
    """One paper's full pipeline (fetch -> LLM extract -> resolve). Runs concurrently
    with other papers' pipelines: the arXiv fetch still queues behind arXiv's own
    (intentionally strict) rate limiter, but that wait now overlaps with other papers'
    LLM/search work instead of blocking behind it."""
    aid = p.source_ids.get("arxiv")
    try:
        # target the sections that actually name prior work — related-work + references
        # (often at the END of the paper, which the old first-6-pages read missed).
        data = await arxiv.fulltext_sections(aid)
        secs = data.get("sections") or {}
        text = "\n\n".join(
            t for t in (secs.get("related_work"), secs.get("introduction"), secs.get("references")) if t
        ) or data.get("full_text", "")
        if not text:
            return {}
        text = text[:20000]
        # complete_json is a blocking sync call (httpx.Client) — run it off the event
        # loop so it doesn't stall every other paper's fetch/search while it's in flight.
        out = await asyncio.to_thread(llm.complete_json, *extract_lineage(p.title, text))
        titles = []
        if isinstance(out, dict):
            for b in out.get("builds_on") or []:
                if isinstance(b, dict) and b.get("title"):
                    titles.append(str(b["title"]))
        if not titles:
            return {}
        hit_lists = await asyncio.gather(*(source.search(t, limit=1) for t in titles[:8]))
    except Exception:  # noqa: BLE001 — one paper's failure shouldn't sink the whole batch
        return {}
    found: dict[str, Paper] = {}
    ref_ids: list[str] = []
    for t, hits in zip(titles[:8], hit_lists):
        if hits and _overlap(t, hits[0].title) >= 2:  # guard against wrong matches
            hit = hits[0]
            found.setdefault(hit.id, hit)
            ref_ids.append(hit.id)
    if ref_ids:
        p.referenced_works = list(dict.fromkeys(list(p.referenced_works) + ref_ids))
        if on_event:
            on_event({"i": -1, "agent": "frontier", "type": "note",
                      "content": f"{p.title[:45]}: linked {len(ref_ids)} predecessors via full-text"})
    return found


async def link_frontier_papers(
    papers: list[Paper], source, arxiv, llm: LLMClient, settings, on_event=None
) -> list[Paper]:
    """For each arXiv frontier paper (processed concurrently): read its PDF, extract
    the works it builds on, resolve them via OpenAlex, populate `referenced_works` (so
    edges form), and return the resolved predecessor papers to add to the graph."""
    if arxiv is None or not llm.available:
        return []
    targets = [p for p in papers if p.source_ids.get("arxiv")]
    if not targets:
        return []
    results = await asyncio.gather(*(_link_one(p, source, arxiv, llm, on_event) for p in targets))
    extra: dict[str, Paper] = {}
    for found in results:
        extra.update(found)
    return list(extra.values())
