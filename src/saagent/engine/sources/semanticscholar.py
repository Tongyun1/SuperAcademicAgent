"""Semantic Scholar citation-count enrichment.

OpenAlex citation counts are wrong for some papers — e.g. "Attention Is All You
Need" comes back as 6576 (a broken/re-indexed record) when the real count is
~182k. Semantic Scholar, looked up by arXiv id or DOI, returns the accurate
count, so we use it to *correct* citation_count on graph nodes before metrics
(PageRank / velocity) and founding are computed. OpenAlex stays the primary
source; S2 only overwrites the citation number when it has a better one.

Best-effort by design: on rate limits (HTTP 429, common without an API key) or
any network error we back off a few times and then give up silently — the graph
still works with OpenAlex counts. Results are cached (per id) so repeat runs and
re-analysis never re-hit the API. Set S2_API_KEY to avoid the rate limit.
"""
from __future__ import annotations

import time

import httpx

from ..store.cache import Cache

_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
_BACKOFF = (2, 5, 10, 20)  # seconds between retries on 429 / transient errors
_MAX_IDS = 500  # S2 batch cap per request


def _s2_id(doi: str | None, arxiv: str | None) -> str | None:
    """Map our ids to a Semantic Scholar id string (prefer arXiv, then DOI)."""
    if arxiv:
        return f"ARXIV:{arxiv}"
    if doi:
        d = doi.replace("https://doi.org/", "").replace("http://doi.org/", "").strip()
        if d:
            return f"DOI:{d}"
    return None


def _fetch_counts(s2ids: list[str], api_key: str | None) -> dict[str, int]:
    """POST the S2 batch endpoint for citationCount. Returns {s2id: count} (found only)."""
    headers = {"x-api-key": api_key} if api_key else {}
    for attempt, wait in enumerate((*_BACKOFF, None)):
        try:
            with httpx.Client(timeout=25.0) as c:
                r = c.post(
                    _BATCH_URL,
                    params={"fields": "citationCount,externalIds"},
                    json={"ids": s2ids},
                    headers=headers,
                )
            if r.status_code == 429:
                if wait is None:
                    return {}
                time.sleep(wait)
                continue
            r.raise_for_status()
            out: dict[str, int] = {}
            # response list is positionally aligned with the request ids (null = not found)
            for sent, got in zip(s2ids, r.json()):
                if got and isinstance(got.get("citationCount"), int):
                    out[sent] = got["citationCount"]
            return out
        except Exception:  # noqa: BLE001 — network hiccup; back off and retry
            if wait is None:
                return {}
            time.sleep(wait)
    return {}


def enrich_citations(graph, settings, cache: Cache | None = None, trace=None) -> int:
    """Correct citation_count on graph nodes using Semantic Scholar.

    Walks nodes that carry an arXiv id or DOI, batch-fetches accurate counts
    (cache-first), and overwrites node/paper citation_count when S2's count is
    higher (keeps the original in metrics['cite_raw'] for audit). Returns the
    number of papers corrected. Never raises — enrichment is best-effort.
    """
    if not getattr(settings, "s2_enrich", True):
        return 0

    # collect (paper_id, s2id) for nodes we can resolve
    pid_to_s2: dict[str, str] = {}
    for n in graph.nodes:
        p = graph.papers.get(n.paper_id)
        if not p:
            continue
        sid = _s2_id(p.doi, (p.source_ids or {}).get("arxiv"))
        if sid:
            pid_to_s2[n.paper_id] = sid
    if not pid_to_s2:
        return 0

    # cache-first: only hit the network for ids we haven't seen
    counts: dict[str, int] = {}
    missing: list[str] = []
    for sid in set(pid_to_s2.values()):
        cached = cache.get(f"s2cite:{sid}") if cache else None
        if cached is not None:
            counts[sid] = cached
        else:
            missing.append(sid)

    for i in range(0, len(missing), _MAX_IDS):
        chunk = missing[i : i + _MAX_IDS]
        fetched = _fetch_counts(chunk, getattr(settings, "s2_api_key", None))
        for sid in chunk:
            val = fetched.get(sid, -1)  # -1 = known-missing, cached to avoid refetch
            counts[sid] = val
            if cache:
                cache.set(f"s2cite:{sid}", val)

    corrected = 0
    for pid, sid in pid_to_s2.items():
        s2c = counts.get(sid, -1)
        if s2c is None or s2c < 0:
            continue
        n = graph.node(pid)
        p = graph.papers.get(pid)
        old = (n.citation_count if n else 0) or 0
        if s2c > old:  # S2 is authoritative when it knows more citations
            if n:
                n.metrics = {**(n.metrics or {}), "cite_raw": old, "cite_source": "s2"}
                n.citation_count = s2c
            if p:
                p.citation_count = s2c
            corrected += 1

    if trace is not None and corrected:
        trace.add("agent", "note", f"S2 citation enrichment: corrected {corrected} paper(s)")
    return corrected
