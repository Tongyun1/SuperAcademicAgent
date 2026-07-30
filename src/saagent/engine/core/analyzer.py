"""Step C5: synthesize a comprehensive field report."""
from __future__ import annotations

from ..llm.base import LLMClient
from ..llm.prompts import analyze as analyze_prompt
from ..models import CitationGraph, FieldReport, Roadmap, SeedAnalysis, Stage


_VALID_ROLES = {"founding", "breakthrough", "improvement", "branch", "survey", "normal"}


def _build_seed_payload(graph: CitationGraph, seed_id: str | None) -> dict | None:
    """Build the seed dict passed to the analyze prompt."""
    if not seed_id or seed_id not in graph.papers:
        return None
    p = graph.papers[seed_id]
    return {
        "id": seed_id,
        "title": p.title or "",
        "year": p.year,
        "abstract": (p.abstract or "")[:600],
    }


def _parse_seed_analysis(out: dict, graph: CitationGraph, seed_id: str, main_line: list[str], stages: list[Stage]) -> SeedAnalysis | None:
    """Extract and validate seed_analysis from the LLM output. Falls back to
    heuristic values (from the graph itself) if any field is missing/invalid.

    Returns None if the LLM produced no meaningful analysis (both summary and
    relation_to_main_line empty) — the frontend will hide the seed section.
    """
    p = graph.papers.get(seed_id)
    title = p.title if p else ""
    year = p.year if p else None

    raw = out.get("seed_analysis") if isinstance(out.get("seed_analysis"), dict) else {}

    summary = raw.get("summary") if isinstance(raw.get("summary"), str) else ""
    relation = raw.get("relation_to_main_line") if isinstance(raw.get("relation_to_main_line"), str) else ""
    summary = summary.strip()
    relation = relation.strip()
    if not summary and not relation:
        return None

    role = raw.get("role_in_field")
    if role not in _VALID_ROLES:
        for rn in graph.nodes:
            if rn.paper_id == seed_id and rn.role in _VALID_ROLES:
                role = rn.role
                break
        else:
            role = None

    on_main = raw.get("on_main_line")
    if not isinstance(on_main, bool):
        on_main = seed_id in main_line

    stage_name = raw.get("stage_name")
    if not (isinstance(stage_name, str) and stage_name.strip()):
        stage_name = None
        for s in stages:
            if seed_id in (s.papers or []):
                stage_name = s.name
                break

    return SeedAnalysis(
        paper_id=seed_id,
        title=title,
        year=year,
        role_in_field=role,
        on_main_line=on_main,
        stage_name=stage_name,
        summary=summary,
        relation_to_main_line=relation,
    )


def _heuristic_seed_analysis(graph: CitationGraph, seed_id: str | None, main_line: list[str], stages: list[Stage]) -> SeedAnalysis | None:
    """No LLM = no seed analysis. Frontend will hide the section."""
    return None


def analyze(
    graph: CitationGraph,
    roadmap: Roadmap,
    founding: list[str],
    llm: LLMClient,
    query: str,
    seed_id: str | None = None,
) -> FieldReport:
    key_payload = [
        {
            "id": rn.paper_id,
            "title": rn.title,
            "year": rn.year,
            "role": rn.role,
            "abstract": (graph.papers[rn.paper_id].abstract or "")[:360]
            if rn.paper_id in graph.papers
            else "",
        }
        for rn in roadmap.nodes
    ]

    seed_payload = _build_seed_payload(graph, seed_id)

    if llm.available and key_payload:
        out = llm.complete_json(*analyze_prompt(query, key_payload, seed=seed_payload))
        if not isinstance(out, dict):
            import sys
            print(f"  [analyzer] LLM returned {type(out).__name__}, falling back to heuristic report", file=sys.stderr)
        if isinstance(out, dict):
            valid = {n.paper_id for n in graph.nodes}

            def keep(ids):
                return [i for i in (ids or []) if i in valid]

            stages = [
                Stage(
                    name=s.get("name", ""),
                    period=s.get("period"),
                    summary=s.get("summary", ""),
                    headline=(s.get("headline") or None),
                    papers=keep(s.get("papers")),
                )
                for s in out.get("stages", [])
                if isinstance(s, dict)
            ]

            reasons_raw = out.get("must_read_reasons") or {}
            must_read_reasons = {
                pid: str(reason).strip()
                for pid, reason in reasons_raw.items()
                if isinstance(pid, str) and pid in valid and isinstance(reason, str) and reason.strip()
            } if isinstance(reasons_raw, dict) else {}

            def _s(key):
                v = out.get(key)
                return v.strip() if isinstance(v, str) and v.strip() else None

            glossary_raw = out.get("glossary") or {}
            glossary = {
                str(k).strip(): str(v).strip()
                for k, v in glossary_raw.items()
                if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip()
            } if isinstance(glossary_raw, dict) else {}

            def _slist(key):
                return [str(x).strip() for x in (out.get(key) or []) if isinstance(x, str) and x.strip()]

            main_line = keep(out.get("main_line"))
            seed_paper = _parse_seed_analysis(out, graph, seed_id, main_line, stages) if seed_id else None

            return FieldReport(
                query=query,
                founding_papers=founding,
                stages=stages,
                main_line=main_line,
                gaps=[g for g in out.get("gaps", []) if isinstance(g, str)],
                reading_path=keep(out.get("reading_path")),
                must_read=keep(out.get("must_read")),
                must_read_reasons=must_read_reasons,
                narrative=str(out.get("narrative", "")),
                cover_title=_s("cover_title"),
                cover_blurb=_s("cover_blurb"),
                tldr=_s("tldr"),
                core_idea=_s("core_idea"),
                prerequisites=_slist("prerequisites"),
                glossary=glossary,
                getting_started=_slist("getting_started"),
                seed_paper=seed_paper,
            )

    return _heuristic_report(graph, roadmap, founding, query, seed_id=seed_id)


def _heuristic_report(
    graph: CitationGraph, roadmap: Roadmap, founding: list[str], query: str, seed_id: str | None = None,
) -> FieldReport:
    nodes = [n for n in roadmap.nodes if n.year]
    nodes.sort(key=lambda n: n.year or 0)
    main_line = [n.paper_id for n in nodes]

    stages: list[Stage] = []
    if nodes:
        years = [n.year for n in nodes if n.year]
        y0, y1 = min(years), max(years)
        if y1 - y0 <= 3:
            buckets = [(y0, y1)]
        else:
            mid = (y0 + y1) // 2
            buckets = [(y0, mid), (mid + 1, y1)]
        labels = ["萌芽/奠基", "发展/繁荣", "成熟/前沿"]
        for idx, (a, b) in enumerate(buckets):
            ps = [n.paper_id for n in nodes if n.year and a <= n.year <= b]
            stages.append(
                Stage(
                    name=labels[min(idx, len(labels) - 1)],
                    period=f"{a}-{b}",
                    headline=None,
                    summary=f"{a}-{b} 年间该领域的关键论文。",
                    papers=ps,
                )
            )

    by_pr = sorted(
        graph.nodes, key=lambda n: n.metrics.get("pagerank", 0.0), reverse=True
    )
    must_read = [n.paper_id for n in by_pr[:5]]
    reading_path = list(dict.fromkeys(founding + main_line))

    years = [n.year for n in graph.nodes if n.year]
    span = f"{min(years)}–{max(years)}" if years else "n/a"
    cover_blurb = (
        f"A citation-graph trace of {len(graph.nodes)} works across {span}, "
        f"distilled into {len(roadmap.nodes)} key papers."
    )

    return FieldReport(
        query=query,
        founding_papers=founding,
        stages=stages,
        main_line=main_line,
        gaps=["(纯图算法模式：未生成研究空白分析，配置 LLM 后可得)"],
        reading_path=reading_path,
        must_read=must_read,
        must_read_reasons={},
        narrative=(
            f"基于引用网络（{len(graph.nodes)} 篇论文、{len(graph.edges)} 条引用）的纯图算法分析。"
            f"奠基候选 {len(founding)} 篇，关键论文 {len(roadmap.nodes)} 篇。"
            "配置 LLM 可获得领域叙事、阶段解读与研究空白建议。"
        ),
        cover_blurb=cover_blurb,
        seed_paper=_heuristic_seed_analysis(graph, seed_id, main_line, stages),
        degraded=True,
    )
