"""Deep-read tools: let the agent read a paper's abstract + full text, and connect
citation-disconnected frontier papers to the lineage via full-text understanding.

These ground the agent's judgments (founding / roles / relevance) in what papers
actually say, not just their metadata — and expose the project's headline capability
(frontier full-text link-back) as an agent-driven tool.
"""

from __future__ import annotations

import asyncio
import os

from pydantic import BaseModel, Field

from stirrup import Tool, ToolResult, ToolUseCountMetadata

from ..context import RunContext


def _ok(content: str) -> ToolResult[ToolUseCountMetadata]:
    return ToolResult(content=content, metadata=ToolUseCountMetadata(), success=True)


def _parse_local_pdf(path: str, max_chars: int = 60000) -> str:
    """Extract text from a local PDF using PyMuPDF."""
    import fitz  # PyMuPDF

    doc = fitz.open(path)
    parts = [page.get_text() for page in doc]
    doc.close()
    return "\n".join(parts)[:max_chars].strip()


def _render_sections(sections: dict, full: str, section_filter: str | None, parts: list[str]) -> None:
    """Append section content to parts list based on filter."""
    if sections:
        if section_filter:
            body = sections.get(section_filter) or sections.get(section_filter.replace(" ", "_"))
            if body:
                parts.append(f"[{section_filter.replace('_', ' ').upper()}]\n{body[:18000]}")
            else:
                available = ", ".join(sections.keys())
                parts.append(f"[section '{section_filter}' not found; available: {available}]")
        else:
            order = ["abstract", "introduction", "related_work", "method", "experiments", "conclusion"]
            for name in order:
                body = sections.get(name)
                if body:
                    parts.append(f"[{name.replace('_', ' ').upper()}]\n{body[:9000]}")
    elif full:
        if section_filter:
            parts.append(f"[sections not parseable; returning full text]\n{full[:36000]}")
        else:
            parts.append(f"FULL TEXT:\n{full[:36000]}")


class PaperIdParams(BaseModel):
    paper_id: str = Field(description="A paper id shown in the graph/summary (e.g. 'W2626778328' or 'arxiv:2312.00752').")
    section: str | None = Field(
        default=None,
        description="Optional: request a single section for deep reading (e.g. 'method', 'introduction', "
        "'experiments', 'conclusion', 'abstract', 'related_work'). Omit to get all sections.",
    )


class LocalPdfParams(BaseModel):
    path: str = Field(description="Absolute or relative path to a local PDF file.")
    section: str | None = Field(
        default=None,
        description="Optional: request a single section (e.g. 'method', 'introduction'). Omit to get all sections.",
    )


class LinkFrontierParams(BaseModel):
    paper_ids: list[str] = Field(
        description="One or more paper ids already in the graph to link (e.g. the ones "
        "graph_summary flags as disconnected with an arXiv id available). Pass ALL of them "
        "in a single call rather than one at a time — it's one tool call regardless of how "
        "many ids you pass."
    )


def build_read_tools(ctx: RunContext) -> list[Tool]:
    ws = ctx.ws

    async def _resolve(pid: str):
        return ws.papers.get(pid) or await ctx.source.get_paper(pid)

    async def read_paper(p: PaperIdParams) -> ToolResult[ToolUseCountMetadata]:
        paper = await _resolve(p.paper_id)
        if paper is None:
            return _ok(f"'{p.paper_id}' not found. Use an id from the graph summary or find_candidates.")
        head = (
            f"{paper.title} ({paper.year})\n"
            f"id={paper.id} | citations={paper.citation_count}"
            f"{' | venue=' + paper.venue if paper.venue else ''}\n"
        )
        parts = [head]
        aid = (paper.source_ids or {}).get("arxiv")
        sections: dict = {}
        if aid and ctx.arxiv is not None:
            try:
                data = await ctx.arxiv.fulltext_sections(aid)
                sections = data.get("sections") or {}
                full = data.get("full_text") or ""
            except Exception as e:  # noqa: BLE001
                full = ""
                pdf_url = f"https://arxiv.org/pdf/{aid.split(':')[-1]}"
                parts.append(
                    f"[PDF 下载失败: {e}]\n"
                    f"论文 PDF 链接: {pdf_url}\n"
                    f"请用 ask_user 询问用户是否能帮忙下载此 PDF 到本地，"
                    f"然后用 read_local_pdf 工具读取本地文件路径。"
                )
            else:
                _render_sections(sections, full, p.section, parts)
        # abstract fallback (OpenAlex) when no PDF sections were parsed
        if "abstract" not in sections and paper.abstract:
            parts.insert(1, f"ABSTRACT:\n{paper.abstract}")
        if len(parts) == 1:
            if aid:
                pdf_url = f"https://arxiv.org/pdf/{aid.split(':')[-1]}"
                parts.append(
                    f"[无法获取全文]\n"
                    f"论文 PDF 链接: {pdf_url}\n"
                    f"请用 ask_user 询问用户是否能帮忙下载此 PDF 到本地，"
                    f"然后用 read_local_pdf 工具读取。"
                )
            else:
                parts.append("[no abstract or arXiv full text available for this paper]")
        ws.trace.add("agent", "read", f"{paper.id} | {paper.title[:60]}")
        return _ok("\n\n".join(parts))

    async def read_local_pdf(p: LocalPdfParams) -> ToolResult[ToolUseCountMetadata]:
        path = os.path.expanduser(p.path)
        if not os.path.isfile(path):
            return _ok(f"文件不存在: {path}")
        try:
            from ..engine.sources.arxiv import split_sections
            text = await asyncio.to_thread(_parse_local_pdf, path)
        except Exception as e:  # noqa: BLE001
            return _ok(f"PDF 解析失败: {e}")
        if not text:
            return _ok(f"PDF 解析结果为空: {path}")
        sections = split_sections(text)
        parts = [f"[LOCAL PDF] {os.path.basename(path)}\n"]
        _render_sections(sections, text, p.section, parts)
        if len(parts) == 1:
            parts.append(f"FULL TEXT:\n{text[:36000]}")
        return _ok("\n\n".join(parts))

    async def link_frontier(p: LinkFrontierParams) -> ToolResult[ToolUseCountMetadata]:
        if not ctx.llm.available:
            return _ok("link_frontier needs an LLM to extract prior works from the PDF; none configured.")
        targets = []
        skipped = []
        for pid in p.paper_ids:
            paper = ws.papers.get(pid)
            if paper is None:
                skipped.append(f"{pid} (not in graph — add it first)")
            elif not (paper.source_ids or {}).get("arxiv"):
                skipped.append(f"{pid} (no arXiv id — full-text link-back needs a PDF)")
            elif paper.referenced_works:
                skipped.append(f"{pid} (already has reference data from OpenAlex — use expand_backward instead)")
            elif pid in ws.link_attempted:
                skipped.append(f"{pid} (already tried link_frontier — no predecessors resolved last time, retrying won't help)")
            else:
                targets.append(paper)
        if not targets:
            return _ok("link_frontier: nothing linkable.\nSkipped: " + "; ".join(skipped))
        from saagent.engine.core.frontier import link_frontier_papers

        ws.link_attempted.update(t.id for t in targets)
        extra = await link_frontier_papers(targets, ctx.source, ctx.arxiv, ctx.llm, ctx.settings)
        depth = min((ws.depth.get(t.id, 0) for t in targets), default=0) + 1
        added = sum(ws.add_paper(pp, depth) for pp in extra)
        ws.trace.add("agent", "link_frontier", f"{[t.id for t in targets]}: +{added} predecessors")
        lines = [
            f"link_frontier: read {len(targets)} PDF(s), extracted and wired in {added} new "
            f"predecessor(s) total (edges form on the next graph build)."
        ]
        for t in targets:
            lines.append(f"  {t.id} | {t.title[:60]}")
        if skipped:
            lines.append("Skipped: " + "; ".join(skipped))
        lines.append(ws.summary())
        return _ok("\n".join(lines))

    return [
        Tool[PaperIdParams, ToolUseCountMetadata](
            name="read_paper",
            description=(
                "Read a paper's abstract and (if on arXiv) its full text. Use this to GROUND "
                "your judgments — before confirming the founding paper, assigning roadmap roles, "
                "or writing the report — instead of guessing from title + citation count. "
                "For deep reading, pass section='method' (or introduction/experiments/conclusion) "
                "to get a single section with more text (18k chars vs 9k)."
            ),
            parameters=PaperIdParams,
            executor=read_paper,
        ),
        Tool[LinkFrontierParams, ToolUseCountMetadata](
            name="link_frontier",
            description=(
                "Connect recent, citation-disconnected papers to the lineage: read each PDF, "
                "extract the prior works it builds on, and wire them in as references. Accepts "
                "MULTIPLE paper_ids — pass them all at once (graph_summary flags exactly which "
                "disconnected ids have arXiv full text available) instead of calling this "
                "repeatedly. Use whenever graph_summary shows a nontrivial fraction of the graph "
                "with zero citation edges, not just on individual floaters you happen to notice."
            ),
            parameters=LinkFrontierParams,
            executor=link_frontier,
        ),
        Tool[LocalPdfParams, ToolUseCountMetadata](
            name="read_local_pdf",
            description=(
                "Read a local PDF file for deep reading. Use when: (1) the user provides a local "
                "file path, or (2) arXiv PDF download failed and the user downloaded the file manually. "
                "Supports the same section parameter as read_paper."
            ),
            parameters=LocalPdfParams,
            executor=read_local_pdf,
        ),
    ]
