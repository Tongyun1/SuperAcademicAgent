"""Step C6 (partial): export results to JSON / GraphML / Markdown."""
from __future__ import annotations

import json
import os

import networkx as nx

from .models import PipelineResult


def _title(result: PipelineResult, pid: str) -> str:
    p = result.graph.papers.get(pid)
    if not p:
        n = result.graph.node(pid)
        return n.title if n else pid
    yr = f" ({p.year})" if p.year else ""
    return f"{p.title}{yr}"


def to_json(result: PipelineResult, path: str) -> None:
    _ensure_parent(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result.model_dump(), f, ensure_ascii=False, indent=2)


def to_graphml(result: PipelineResult, path: str) -> None:
    _ensure_parent(path)
    g = nx.DiGraph()
    for n in result.graph.nodes:
        g.add_node(
            n.paper_id,
            title=n.title or "",
            year=int(n.year) if n.year else -1,
            citation_count=int(n.citation_count),
            role=str(n.role or ""),
            depth=int(n.depth),
            pagerank=float(n.metrics.get("pagerank", 0.0)),
            betweenness=float(n.metrics.get("betweenness", 0.0)),
        )
    for e in result.graph.edges:
        if e.source in g and e.target in g:
            g.add_edge(e.source, e.target, type=e.type)
    nx.write_graphml(g, path)


def roadmap_to_graphml(result: PipelineResult, path: str) -> None:
    _ensure_parent(path)
    g = nx.DiGraph()
    for n in result.roadmap.nodes:
        g.add_node(
            n.paper_id,
            title=n.title or "",
            year=int(n.year) if n.year else -1,
            role=str(n.role or ""),
        )
    for e in result.roadmap.edges:
        if e.source in g and e.target in g:
            g.add_edge(e.source, e.target, relation=e.relation)
    nx.write_graphml(g, path)


def to_markdown(result: PipelineResult, path: str) -> None:
    _ensure_parent(path)
    r = result.report
    lines: list[str] = []
    lines.append(f"# 领域脉络分析报告：{result.query}\n")
    lines.append(
        f"> 引用网络 {len(result.graph.nodes)} 篇论文 / {len(result.graph.edges)} 条引用 · "
        f"LLM：{'开启' if result.llm_used else '关闭（纯图算法）'}\n"
    )

    # --- newcomer guide (Pro/deep report) ---
    if r.tldr:
        lines.append("## 🧭 一分钟入门（写给完全不懂的人）")
        lines.append(r.tldr + "\n")
    if r.core_idea:
        lines.append(f"**核心思想**：{r.core_idea}\n")
    if r.prerequisites:
        lines.append("### 前置知识")
        for x in r.prerequisites:
            lines.append(f"- {x}")
        lines.append("")
    if r.getting_started:
        lines.append("### 🚀 如何入手")
        for i, x in enumerate(r.getting_started, 1):
            lines.append(f"{i}. {x}")
        lines.append("")
    if r.glossary:
        lines.append("### 📖 关键术语")
        for term, defn in r.glossary.items():
            lines.append(f"- **{term}**：{defn}")
        lines.append("")

    # --- seed paper (the one the user actually asked about) ---
    if r.seed_paper and r.seed_paper.paper_id and (
        (r.seed_paper.summary or "").strip() or (r.seed_paper.relation_to_main_line or "").strip()
    ):
        sp = r.seed_paper
        lines.append("## 📌 您所问的论文")
        lines.append(f"**{sp.title}**（{sp.year or '—'}）")
        pos = "位于主干" if sp.on_main_line else "领域分支"
        role = sp.role_in_field or "—"
        stage = f" · {sp.stage_name}" if sp.stage_name else ""
        lines.append(f"- 位置：{pos}{stage} · 角色：{role}")
        if sp.summary:
            lines.append(f"- **论文简介**：{sp.summary}")
        if sp.relation_to_main_line:
            lines.append(f"- **与主干的关系**：{sp.relation_to_main_line}")
        lines.append("")

    lines.append("## 🌱 奠基论文")
    for pid in result.founding:
        lines.append(f"- {_title(result, pid)}")
    lines.append("")

    if r.narrative:
        lines.append("## 📖 领域综述")
        lines.append(r.narrative + "\n")

    if r.stages:
        lines.append("## 🪜 发展阶段")
        for st in r.stages:
            head = f"### {st.name}" + (f"（{st.period}）" if st.period else "")
            lines.append(head)
            if st.summary:
                lines.append(st.summary)
            for pid in st.papers:
                lines.append(f"- {_title(result, pid)}")
            lines.append("")

    if r.main_line:
        lines.append("## 🛣️ 主线脉络（从源头到前沿）")
        for i, pid in enumerate(r.main_line, 1):
            lines.append(f"{i}. {_title(result, pid)}")
        lines.append("")

    if r.must_read:
        lines.append("## ⭐ 必读清单")
        for pid in r.must_read:
            lines.append(f"- {_title(result, pid)}")
        lines.append("")

    if r.reading_path:
        lines.append("## 🧭 推荐阅读顺序")
        for i, pid in enumerate(r.reading_path, 1):
            lines.append(f"{i}. {_title(result, pid)}")
        lines.append("")

    if r.gaps:
        lines.append("## 🔍 研究空白 / 机会")
        for g in r.gaps:
            lines.append(f"- {g}")
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


_TRACE_ICONS = {
    "thought": "[think]", "action": "[tool ]", "observation": "[obs  ]",
    "finish": "[done ]", "verify": "[verify]", "self_correct": "[fix  ]",
    "consistency": "[check]", "note": "[note ]", "error": "[ERROR]",
}


def to_trace_log(result: PipelineResult, path: str) -> None:
    """Human-readable agent trace (the live process) — only when trace is non-empty."""
    _ensure_parent(path)
    lines = [f"# Agent trace — {result.query}", ""]
    for ev in result.trace:
        tag = _TRACE_ICONS.get(ev.get("type", ""), "[· ]")
        c = ev.get("content")
        if isinstance(c, dict):
            c = " ".join(f"{k}={v}" for k, v in c.items())
        c = str(c).replace("\n", " ")
        lines.append(f"{ev.get('i', 0):>3}  {tag} {ev.get('agent','')}: {c}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def export_all(result: PipelineResult, out_dir: str) -> dict[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    paths = {
        "json": os.path.join(out_dir, "result.json"),
        "graphml": os.path.join(out_dir, "citation_network.graphml"),
        "roadmap": os.path.join(out_dir, "roadmap.graphml"),
        "report": os.path.join(out_dir, "report.md"),
        "png": os.path.join(out_dir, "network.png"),
        "html": os.path.join(out_dir, "view.html"),
    }
    to_json(result, paths["json"])
    to_graphml(result, paths["graphml"])
    roadmap_to_graphml(result, paths["roadmap"])
    to_markdown(result, paths["report"])
    if result.trace:  # agent process log (zero extra cost — trace already in memory)
        paths["trace"] = os.path.join(out_dir, "trace.log")
        to_trace_log(result, paths["trace"])
    # visualization (best-effort: don't fail the whole export if a renderer errors)
    from . import viz

    try:
        viz.to_png(result, paths["png"])
    except Exception:
        paths.pop("png", None)
    try:
        viz.to_html(result, paths["html"])
    except Exception:
        paths.pop("html", None)
    return paths


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
