"""Prompt templates (versioned). Keep outputs strict JSON for reproducibility."""
from __future__ import annotations

PROMPT_VERSION = "v0.2"

SYSTEM = (
    "You are a meticulous research librarian and bibliometric analyst. "
    "You reason about how a research field evolved from real citation data. "
    "Always answer with STRICT JSON only, no prose outside the JSON."
)


def resolve_intent(text: str) -> tuple[str, str]:
    user = f"""A user described a research interest in free text. Extract a concise search intent.

User text:
\"\"\"{text}\"\"\"

Return JSON:
{{"keywords": "<3-8 word search query in English>", "field": "<short field name>"}}"""
    return SYSTEM, user


def tag_relevance(query: str, nodes: list[dict]) -> tuple[str, str]:
    """Tag each graph node by relevance to the SPECIFIC topic, so the roadmap stays on
    topic instead of drifting to high-citation general-field papers."""
    lines = [f"{n['id']} | {n.get('year')} | {n.get('title','')[:120]}" for n in nodes]
    user = f"""Topic: "{query}"

Tag each paper by how it relates to THIS SPECIFIC topic (not the broader field):
- "core": specifically about the topic itself — its method, variants, direct improvements,
  surveys of it, or the recent frontier of it.
- "related": adjacent context the topic builds on or is applied within, but NOT specifically
  about the topic (e.g. general Transformer/LLM papers for an "on-policy distillation" query).
- "off-topic": unrelated.

Papers (id | year | title):
{chr(10).join(lines)}

Return JSON: {{"tags": {{"<id>": "core|related|off-topic", ...for every id}}}}"""
    return SYSTEM, user


def extract_lineage(paper_title: str, fulltext: str) -> tuple[str, str]:
    """From a paper's intro/related-work, extract the key prior works it builds on.
    This is how a brand-new paper (no citations, not yet indexed) gets connected to the
    lineage — the connection comes from the TEXT, not the citation graph."""
    user = f"""Paper: "{paper_title}"

Below is its introduction / related-work (PDF excerpt). Extract the KEY prior works this
paper explicitly BUILDS ON, EXTENDS, or directly compares against — i.e. its lineage.
Give each by the paper TITLE as written in the text. Exclude generic background; keep the
ones this work genuinely descends from (5-10 max).

Excerpt:
\"\"\"{fulltext}\"\"\"

Return JSON: {{"builds_on": [{{"title": "<exact paper title>", "relation": "<extends|improves|compares|inspired-by>"}}]}}"""
    return SYSTEM, user


def select_seeds(query: str, candidates: list[dict]) -> tuple[str, str]:
    """Pick the best seed paper(s) for a topic from real candidates (OpenAlex + arXiv).
    Relevance gating: reject papers that only share a generic word with the query."""
    lines = []
    for c in candidates:
        lines.append(
            f"[{c['idx']}] ({c.get('source')}) {c.get('year')} | cites={c.get('citation_count')} "
            f"| {c.get('title','')[:150]}"
        )
    user = f"""A user wants the development lineage of this exact topic: "{query}"

Candidate seed papers (from OpenAlex citation DB + newest arXiv):
{chr(10).join(lines)}

Pick the 1-3 candidates that BEST represent EXACTLY this topic — the right starting point
to map the field. Rules:
- REJECT papers that only share a generic word with the query but are about something else
  (e.g. for "on-policy distillation", reject an economics paper about "knowledge spillovers").
- If the topic is an established field, prefer its most representative/seminal paper.
- If it's an emerging/recent direction, prefer the most on-topic recent papers (arXiv).
- If NONE are truly on-topic, return an empty list.

Return JSON: {{"chosen": [<idx>, ...], "reason": "<one line>"}}"""
    return SYSTEM, user


def _fmt_candidates(cands: list[dict]) -> str:
    lines = []
    for c in cands:
        vel = c.get("velocity")
        vtxt = f" | velocity={vel}/yr" if vel is not None else ""
        pr = c.get("pagerank")
        prtxt = f" | pagerank={pr}" if pr is not None else ""
        rel = c.get("relevance")
        reltxt = f" | {rel}" if rel else ""
        lines.append(
            f"- id={c['id']} | year={c.get('year')} | citations={c.get('citation_count')}"
            f"{vtxt}{prtxt}{reltxt} | {c.get('title','')[:140]}"
        )
    return "\n".join(lines)


def _fmt_founding_candidates(cands: list[dict]) -> str:
    lines = []
    for c in cands:
        seed = " [SEED — the paper representing this field]" if c.get("is_seed") else ""
        lines.append(
            f"- id={c['id']} | year={c.get('year')} | global_citations={c.get('citation_count')} "
            f"| in_field_citations={c.get('cited_in_field')} "
            f"| network_centrality={c.get('centrality')}{seed}"
        )
        lines.append(f"    title: {c.get('title','')[:160]}")
        abs = (c.get("abstract") or "").strip()
        if abs:
            lines.append(f"    abstract: {abs[:500]}")
    return "\n".join(lines)


def pick_founding(query: str, candidates: list[dict], seed_title: str | None = None) -> tuple[str, str]:
    seed_line = (
        f'\nThe user\'s entry point (seed) is: "{seed_title}". '
        "The field is the line of research this paper belongs to."
        if seed_title
        else ""
    )
    user = f"""Field / query: "{query}"{seed_line}

Trace the FOUNDING / seminal paper(s) of THIS specific field — the work(s) that introduced
the *core idea* the field is built on. Decide ONLY from the evidence below (abstracts +
citation signals). Do NOT rely on your prior memory of these papers; if evidence is thin, say so.

How to judge (like an expert doing a literature review):
- The founding paper is usually the most CENTRAL paper inside this field's own citation network
  (high `in_field_citations` / `network_centrality`) AND its abstract states it *introduces /
  proposes* the core method — not a later application of it.
- A paper is NOT the founding paper, however old or globally cited, if its abstract shows it is
  tangential: a dataset / benchmark / corpus / toolkit, or a general-purpose method borrowed from
  another field (e.g. a generic vision backbone for an NLP field). High `global_citations` with low
  `in_field_citations` is a red flag for such outliers.
- The SEED is the user's ENTRY POINT, NOT automatically the founding. A recent seed is very often
  an application / extension / improvement, not the origin. If the seed's abstract says it "builds
  on / extends / applies / improves" prior work, or it is recent with low `in_field_citations`, it
  is NOT the founding — trace back to the earlier paper it builds on. Only pick the seed itself as
  founding when the evidence shows IT introduced the field's core idea (early, central, its abstract
  says "we propose/introduce" the core method). When unsure, prefer the older progenitor over the seed.

Candidates:
{_fmt_founding_candidates(candidates)}

Return JSON:
{{"founding": ["<id>", ...1-3, best first],
  "reasoning": "<2-3 sentences citing the abstract + why it is central to THIS field>"}}"""
    return SYSTEM, user


def curate_survey_refs(
    query: str, surveys: list[dict], candidates: list[dict]
) -> tuple[str, str]:
    """Ask the model to read recent surveys and pick the field-relevant key references,
    discarding generic background a survey inevitably cites (stats, old ML, datasets)."""
    survey_block = "\n".join(
        f"- ({s.get('year')}) {s.get('title','')[:140]}\n    {(s.get('abstract') or '')[:400]}"
        for s in surveys
    )
    user = f"""Field / query: "{query}"

These are recent SURVEYS of the field (expert maps). Read them:
{survey_block}

Below are papers cited by those surveys. Select ONLY the ones that are central to THIS
field — its founding work, milestone methods, important branches, and the recent FRONTIER
(use year + velocity to spot frontier with few citations). DISCARD generic background a
survey routinely cites: statistics/optimization classics, datasets/benchmarks, and methods
borrowed from unrelated fields.

Candidate references:
{_fmt_candidates(candidates)}

Return JSON: {{"key_papers": ["<id>", ...]}}  — only ids that appear above."""
    return SYSTEM, user


def filter_and_roadmap(query: str, candidates: list[dict]) -> tuple[str, str]:
    user = f"""Field / query: "{query}"

Below is the FULL on-topic candidate set from a citation network, each with signals
(year, citation_count, velocity=citations/yr, pagerank, relevance). Select the KEY
papers that actually drove the field's evolution (new paradigm, key improvement,
opened a branch, definitive survey). Then describe the development roadmap as directed
evolution edges (earlier paper -> later paper it influenced).

Choose HOW MANY yourself — there is NO target count. Include every paper that genuinely
shapes the lineage and omit the rest; a smaller accurate roadmap beats a padded one.
Read the signals: high pagerank/citations = structurally important; high velocity + recent
year = frontier even with few citations; relevance=related can still be a key offspring
(e.g. GPT-4/LLaMA for "attention") — judge on merit, not on the tag.

IMPORTANT — span the FULL arc, root to frontier:
- Include the field's foundational ORIGIN as the root, even if it comes from the broader
  parent field (e.g. the original knowledge-distillation / policy-distillation paper for an
  "on-policy distillation" query). Don't let the roadmap appear to "start" at recent work.
- Also cover the FRONTIER, not just the classics: recent papers have few citations only
  because they are new — use `velocity` (citations/year) and year to spot them and
  DELIBERATELY include the notable recent works (last 2-3 years) so the roadmap reaches today.

Papers:
{_fmt_candidates(candidates)}

Assign each selected paper a role from:
  founding | breakthrough | improvement | branch | survey
Role definitions:
- founding: the original paper that started this line of research.
- breakthrough: introduced a new paradigm or technique that reshaped the field.
- improvement: significantly improved an existing method (not a new paradigm).
- branch: opened a distinct sub-direction or applied the main idea to a new domain.
- survey: a comprehensive literature REVIEW that synthesizes many papers. ONLY use this \
  for actual survey/review papers that are explicitly structured as an overview of the \
  field. Do NOT use "survey" for papers that criticize, re-evaluate, or empirically test \
  assumptions of the field — those are "improvement" or "branch" even if they discuss \
  many related works.

Return JSON:
{{"key_papers": [{{"id": "<id>", "role": "<role>", "contribution": "<one concrete sentence: what this paper actually did, in plain English>"}}],
  "edges": [{{"source": "<earlier id>", "target": "<later id>", "relation": "leads_to|improves|inspires|branches"}}]}}
Only use ids that appear above. Keep each contribution sharp and specific (≤22 words); avoid filler like "this paper presents…"."""
    return SYSTEM, user


def _fmt_key_papers(key_papers: list[dict]) -> str:
    lines = []
    for p in key_papers:
        lines.append(f"- {p['id']} | {p.get('year')} | {p.get('role')} | {p.get('title','')[:130]}")
        a = (p.get("abstract") or "").strip()
        if a:
            lines.append(f"    abstract: {a[:360]}")
    return "\n".join(lines)


def analyze(query: str, key_papers: list[dict], seed: dict | None = None) -> tuple[str, str]:
    seed_block = ""
    seed_schema = ""
    if seed and seed.get("id"):
        seed_abstract = (seed.get("abstract") or "").strip()[:600]
        seed_block = (
            f"\n\nUSER'S SEED PAPER (auto-picked anchor for graph expansion):\n"
            f"- id: {seed.get('id')}\n"
            f"- title: {seed.get('title', '')}\n"
            f"- year: {seed.get('year')}\n"
            + (f"- abstract: {seed_abstract}\n" if seed_abstract else "")
            + "IMPORTANT — decide whether the seed matters to the user:\n"
              f"  The user's original query was: \"{query}\"\n"
              "  - If the query is a SPECIFIC PAPER REFERENCE (title / DOI / arXiv id closely "
              "matching the seed's title, or clearly pointing at a single paper), the user actively "
              "wants to know about THIS paper — fill `seed_analysis` with a real analysis.\n"
              "  - If the query is a BROAD FIELD/TOPIC NAME (e.g. 'reinforcement learning', "
              "'diffusion models') and the seed was just auto-picked as an anchor, the seed itself "
              "is not what the user asked about — set `seed_analysis.summary` and "
              "`seed_analysis.relation_to_main_line` to empty strings (\"\"). The frontend will "
              "hide the seed section entirely in that case."
        )
        seed_schema = (
            ',\n  "seed_analysis": {\n'
            '    "on_main_line": <true/false — is this seed on the main_line list you produced>,\n'
            '    "stage_name": "<name of the stage this seed falls in, from stages above; null if it is a tangential branch>",\n'
            '    "role_in_field": "<founding|breakthrough|improvement|branch|survey|normal — survey ONLY for actual review/survey papers, NOT for criticism/re-evaluation papers>",\n'
            '    "summary": "<1-2 plain-language sentences: what THIS specific paper is and does; empty string if the query was a broad topic and the user did NOT ask about this specific paper>",\n'
            '    "relation_to_main_line": "<2-3 sentences: where this paper sits relative to the field arc; empty string if the query was a broad topic and the user did NOT ask about this specific paper>"\n'
            "  }"
        )

    user = f"""Field / query: "{query}"
{seed_block}
You are writing the definitive onboarding report for this field. Your reader is SMART
but knows ABSOLUTELY NOTHING about this topic. After reading, they must (1) understand
what the field is and its core idea in plain language, and (2) know exactly how to get
started. Explain jargon; never assume prior knowledge. Ground everything in the papers below.

Key papers (id | year | role | title + abstract):
{_fmt_key_papers(key_papers)}

Output strict JSON ONLY.

Return JSON:
{{"tldr": "<2-4 plain-language sentences: what this field is and why it matters, for a total beginner>",
  "core_idea": "<the single key insight the field is built on, explained in plain terms, ≤40 words>",
  "prerequisites": ["<concept/skill a newcomer should know first, with 3-6 words why>", ...3-6 items],
  "glossary": {{"<key term>": "<plain-language definition a beginner understands>", ...5-10 core terms}},
  "getting_started": ["<concrete first step: what to read/do, and why, in order>", ...4-6 steps],
  "cover_title": "<a polished, publication-quality title naming THIS field/story — academic yet evocative and literary, the kind a review article or a museum exhibition might bear. Do NOT echo the user's raw request or use verbs like 'search/find/survey of'; distill the actual subject into a real title, ≤8 words>",
  "cover_blurb": "<single-sentence epigraph for the cover, ≤24 words, evokes the field's arc>",
  "stages": [{{"name": "<stage>", "period": "<years>",
                "headline": "<≤14-word punchy line (no trailing period)>",
                "summary": "<1-2 sentences in plain language>", "papers": ["<id>", ...]}}],
  "main_line": ["<id>", ... ordered from origin to frontier],
  "gaps": ["<open problem / where the field is heading>", ...],
  "reading_path": ["<id>", ... recommended reading order for a newcomer],
  "must_read": ["<id>", ... — the papers a newcomer truly must read; YOU choose how many, no fixed count, essential-only (quality over quantity)],
  "must_read_reasons": {{"<paper id>": "<why a newcomer must read this, ≤20 words>", ...}},
  "narrative": "<a few sentences telling the story of the field, plain language>"{seed_schema}}}
Only use paper ids from the list above. Every id in must_read should appear in must_read_reasons."""
    return SYSTEM, user


TRANSLATE_SYSTEM = (
    "You are a bilingual academic translator. Translate the user-provided JSON values from "
    "English to Simplified Chinese (zh-CN), preserving JSON structure exactly. Keep the same "
    "keys; only the string values change. Rules: keep proper nouns / technical terms in their "
    "original Latin form when that is what Chinese scientific writing uses (Transformer, BERT, "
    "GPT, CNN, RNN, PageRank, self-attention 可写作'自注意力', attention 写作'注意力'). Translate "
    "every English string in the input, including those inside arrays and nested objects, and "
    "values inside the must_read_reasons mapping. Keep quotation marks idiomatic (中文用「」或" 
    "保持原引号), keep proper Chinese punctuation. Do NOT translate paper titles — if you "
    "encounter a paper title, return it unchanged. Output strict JSON only, no prose."
)


def translate_report(payload: dict) -> tuple[str, str]:
    user = (
        "Translate every English string value in the following JSON to Simplified Chinese, "
        "preserving the structure and keys exactly. Output only the translated JSON.\n\n"
        + __import__("json").dumps(payload, ensure_ascii=False, indent=2)
    )
    return TRANSLATE_SYSTEM, user
