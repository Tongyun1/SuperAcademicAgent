"""Optional post-processing step: localize the report into other languages.

Collects all user-facing English strings from the pipeline result, asks the LLM
to translate them in one round trip, and writes the result into
`PipelineResult.i18n[locale]`. The front-end falls back to English whenever a
field is missing, so failure here is non-fatal.
"""
from __future__ import annotations

from ..llm.base import LLMClient
from ..llm.prompts import translate_report
from ..models import PipelineResult


def localize(result: PipelineResult, llm: LLMClient, locale: str = "zh") -> None:
    """Translate the user-facing English fields of `result` into `locale`.

    Mutates `result.i18n[locale]` in place. Safe to call when LLM is unavailable:
    it just skips. Always best-effort — any failure leaves the english fallback
    intact and never raises.
    """
    if not llm.available:
        return

    payload = _collect(result)
    if not payload or not _has_any_text(payload):
        return

    try:
        out = llm.complete_json(*translate_report(payload))
    except Exception:
        return

    if not isinstance(out, dict):
        return

    cleaned = _clean(out, payload)
    if cleaned:
        result.i18n[locale] = cleaned


# ---------------------------------------------------------------------------


def _collect(r: PipelineResult) -> dict:
    """Build the translation payload from `r`. Keys mirror the result schema so the
    LLM's reply can be re-attached field-for-field by the front-end."""
    report = r.report
    return {
        "cover_title": report.cover_title,
        "cover_blurb": report.cover_blurb,
        "narrative": report.narrative,
        "tldr": report.tldr,
        "core_idea": report.core_idea,
        "prerequisites": list(report.prerequisites or []),
        "glossary": dict(report.glossary or {}),
        "getting_started": list(report.getting_started or []),
        "gaps": list(report.gaps or []),
        "must_read_reasons": dict(report.must_read_reasons or {}),
        "stages": [
            {
                "paper_id_anchor": _stage_key(s, idx),
                "name": s.name,
                "headline": s.headline,
                "summary": s.summary,
            }
            for idx, s in enumerate(report.stages or [])
        ],
        "roadmap_contributions": {
            n.paper_id: n.contribution
            for n in (r.roadmap.nodes or [])
            if n.contribution
        },
        "seed_paper": (
            {
                "summary": report.seed_paper.summary or "",
                "relation_to_main_line": report.seed_paper.relation_to_main_line or "",
            }
            if report.seed_paper
            else None
        ),
        "ui": {
            # Editor's titles for the page sections — translated alongside the data
            # so a deployment can change them without touching the frontend bundle.
            "edition_agentic": "Agentic edition",
            "edition_deterministic": "Deterministic edition",
            "llm_on": "LLM analysis",
            "llm_off": "Graph-only",
            "field_trace_of": "A Field Trace of",
            "founding_works": "Founding works",
            "abstract": "Abstract",
            "stage": "Stage",
            "works": "works",
            "must_read": "Must read",
            "reading_path": "Reading path",
            "open_problems": "Open problems",
            "what_is_not_solved": "What is not yet solved",
            "citation_index": "Citation index",
            "top_n_by_pagerank": "Top 30 by PageRank",
            "reading_apparatus": "Reading apparatus",
            "for_the_newcomer": "For the newcomer",
            "apparatus": "Apparatus",
            "frontier": "Frontier",
            "index": "Index",
            "full_network": "Full citation network · interactive",
            "marginalia": "Marginalia",
            "ai_reasoning_trace": "AI reasoning trace",
            "events": "events",
            "agents": "agents",
            "authors_notes": "Author's notes",
            "method": "Method",
            "deterministic_no_trace": "Deterministic pipeline · no agentic trace",
            "an_annotated_field_trace": "An annotated field trace",
            "cited": "citations",
            "no_founding": "No founding paper identified.",
            "no_must_read": "No must-read list.",
            "no_reading_path": "No reading path generated.",
            "no_gaps": "No open problems generated.",
            "switch_lang": "中文",
            "sec_seed": "The paper you asked about",
            "seed_on_main_line": "On the main line",
            "seed_off_main_line": "A branch of the field",
            "seed_relation_heading": "How it relates to the main line",
        },
    }


def _stage_key(s, idx: int) -> str:
    """Stable anchor so the frontend can match a translated stage back to its source."""
    return f"stage_{idx}"


def _has_any_text(payload: dict) -> bool:
    if payload.get("cover_title") or payload.get("cover_blurb") or payload.get("narrative"):
        return True
    if payload.get("gaps"):
        return True
    if payload.get("must_read_reasons"):
        return True
    if any(s.get("name") or s.get("summary") or s.get("headline") for s in payload.get("stages", [])):
        return True
    if payload.get("roadmap_contributions"):
        return True
    if payload.get("tldr") or payload.get("core_idea"):
        return True
    if payload.get("prerequisites") or payload.get("getting_started"):
        return True
    if payload.get("glossary"):
        return True
    sp = payload.get("seed_paper") or {}
    if sp.get("summary") or sp.get("relation_to_main_line"):
        return True
    return False


def _clean(out: dict, source: dict) -> dict:
    """Defensive normalization — keep only keys we expect and only string-typed values."""
    cleaned: dict = {}

    if isinstance(out.get("cover_title"), str):
        cleaned["cover_title"] = out["cover_title"].strip()
    if isinstance(out.get("cover_blurb"), str):
        cleaned["cover_blurb"] = out["cover_blurb"].strip()
    if isinstance(out.get("narrative"), str):
        cleaned["narrative"] = out["narrative"].strip()
    if isinstance(out.get("gaps"), list):
        cleaned["gaps"] = [g.strip() for g in out["gaps"] if isinstance(g, str)]
    if isinstance(out.get("must_read_reasons"), dict):
        cleaned["must_read_reasons"] = {
            k: v.strip()
            for k, v in out["must_read_reasons"].items()
            if isinstance(k, str) and isinstance(v, str) and v.strip()
        }

    if isinstance(out.get("stages"), list):
        stages_out = []
        for s in out["stages"]:
            if not isinstance(s, dict):
                continue
            stages_out.append(
                {
                    "paper_id_anchor": s.get("paper_id_anchor"),
                    "name": (s.get("name") or "").strip() or None,
                    "headline": (s.get("headline") or "").strip() or None,
                    "summary": (s.get("summary") or "").strip() or None,
                }
            )
        cleaned["stages"] = stages_out

    if isinstance(out.get("roadmap_contributions"), dict):
        cleaned["roadmap_contributions"] = {
            k: v.strip()
            for k, v in out["roadmap_contributions"].items()
            if isinstance(k, str) and isinstance(v, str) and v.strip()
        }

    if isinstance(out.get("ui"), dict):
        cleaned["ui"] = {
            k: v.strip()
            for k, v in out["ui"].items()
            if isinstance(k, str) and isinstance(v, str) and v.strip()
        }

    if isinstance(out.get("tldr"), str):
        cleaned["tldr"] = out["tldr"].strip()
    if isinstance(out.get("core_idea"), str):
        cleaned["core_idea"] = out["core_idea"].strip()
    if isinstance(out.get("prerequisites"), list):
        cleaned["prerequisites"] = [p.strip() for p in out["prerequisites"] if isinstance(p, str) and p.strip()]
    if isinstance(out.get("getting_started"), list):
        cleaned["getting_started"] = [g.strip() for g in out["getting_started"] if isinstance(g, str) and g.strip()]
    if isinstance(out.get("glossary"), dict):
        cleaned["glossary"] = {
            k: v.strip()
            for k, v in out["glossary"].items()
            if isinstance(k, str) and isinstance(v, str) and v.strip()
        }

    if isinstance(out.get("seed_paper"), dict):
        sp = out["seed_paper"]
        seed_out: dict = {}
        if isinstance(sp.get("summary"), str) and sp["summary"].strip():
            seed_out["summary"] = sp["summary"].strip()
        if isinstance(sp.get("relation_to_main_line"), str) and sp["relation_to_main_line"].strip():
            seed_out["relation_to_main_line"] = sp["relation_to_main_line"].strip()
        if seed_out:
            cleaned["seed_paper"] = seed_out

    return cleaned
