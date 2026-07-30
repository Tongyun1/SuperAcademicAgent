"""Survey-first: mine recent surveys and let the LLM curate their references.

A survey's reference list is an expert-curated map of the field — but also full of
generic background (stats, datasets, borrowed methods). So instead of dumping all
refs (which floods the graph with old background), we let the model READ the surveys
and pick the field-relevant key/frontier works.
"""
from __future__ import annotations

import datetime

from ..llm.base import LLMClient
from ..llm.prompts import curate_survey_refs
from ..models import Paper

_CUR_YEAR = datetime.datetime.now().year


def _velocity(p: Paper) -> float:
    if not p.year:
        return float(p.citation_count)
    return p.citation_count / max(_CUR_YEAR - p.year + 1, 1)


async def curate_survey_papers(query: str, source, llm: LLMClient, settings) -> list[Paper]:
    """Return surveys + the LLM-selected field-relevant references. [] if unavailable."""
    if not getattr(settings, "use_surveys", False) or not llm.available:
        return []
    if not hasattr(source, "search_surveys"):
        return []

    surveys = await source.search_surveys(query, limit=settings.survey_count)
    if not surveys:
        return []

    ref_ids: set[str] = set()
    for s in surveys:
        for r in s.referenced_works[: settings.survey_refs_per]:
            if r:
                ref_ids.add(r)
    refs = await source.get_many(list(ref_ids)) if ref_ids else []
    if not refs:
        return surveys

    # bound the prompt: keep the most impactful/recent refs by velocity
    refs = sorted(refs, key=_velocity, reverse=True)[:100]
    surveys_payload = [
        {"title": s.title, "year": s.year, "abstract": s.abstract} for s in surveys
    ]
    candidates = [
        {
            "id": p.id,
            "title": p.title,
            "year": p.year,
            "citation_count": p.citation_count,
            "velocity": round(_velocity(p), 1),
        }
        for p in refs
    ]
    out = llm.complete_json(*curate_survey_refs(query, surveys_payload, candidates))
    selected_ids = set()
    if isinstance(out, dict):
        selected_ids = {i for i in (out.get("key_papers") or []) if isinstance(i, str)}
    by_id = {p.id: p for p in refs}
    selected = [by_id[i] for i in selected_ids if i in by_id]
    return surveys + selected
