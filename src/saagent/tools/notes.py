"""Deep-reading note tools: take_note + export_notes.

These let the agent persist reading insights in memory (surviving context compression)
and export them as a structured markdown file when the user is ready to save.
"""

from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, Field

from stirrup import Tool, ToolResult, ToolUseCountMetadata

from ..context import ReadingNote, RunContext


def _ok(content: str) -> ToolResult[ToolUseCountMetadata]:
    return ToolResult(content=content, metadata=ToolUseCountMetadata(), success=True)


class TakeNoteParams(BaseModel):
    paper_id: str = Field(description="The paper id this note is about.")
    paper_title: str = Field(description="Human-readable title of the paper.")
    section: str = Field(
        description="Which section/aspect the note covers (e.g. 'method', 'introduction', "
        "'experiments', 'overall', 'vs_other_paper')."
    )
    content: str = Field(description="The insight, explanation, or resolved confusion to record.")
    note_type: str = Field(
        default="insight",
        description="Category: 'insight' | 'key_finding' | 'confusion_resolved' | 'comparison'.",
    )


class ExportNotesParams(BaseModel):
    filename: str = Field(
        description="A concise, human-readable filename (without .md extension) for this paper's notes. "
        "Should relate to the paper's topic/title, e.g. 'RLHF_Ziegler2019_精读' or 'PPO_reward_model_notes'. "
        "Use underscores or hyphens, no spaces.",
    )
    paper_id: str | None = Field(
        default=None,
        description="Paper id to export notes for. If omitted, exports notes for the most recently noted paper.",
    )


_NOTE_TYPE_HEADINGS = {
    "key_finding": "关键发现",
    "insight": "深度洞察",
    "confusion_resolved": "疑惑与解答",
    "comparison": "跨论文对比",
}


def build_note_tools(ctx: RunContext) -> list[Tool]:

    def take_note(p: TakeNoteParams) -> ToolResult[ToolUseCountMetadata]:
        note = ReadingNote(
            paper_id=p.paper_id,
            paper_title=p.paper_title,
            section=p.section,
            content=p.content,
            note_type=p.note_type,
        )
        ctx.reading_notes.append(note)
        ctx.ws.trace.add("agent", "take_note", f"{p.paper_id} [{p.section}] ({p.note_type})")
        return _ok(f"Note recorded. Total notes: {len(ctx.reading_notes)}")

    def export_notes(p: ExportNotesParams) -> ToolResult[ToolUseCountMetadata]:
        if not ctx.reading_notes:
            return _ok("No reading notes to export. Use take_note first.")

        by_paper: dict[str, list[ReadingNote]] = defaultdict(list)
        for n in ctx.reading_notes:
            by_paper[n.paper_id].append(n)

        target_id = p.paper_id
        if target_id is None:
            target_id = ctx.reading_notes[-1].paper_id
        notes = by_paper.get(target_id)
        if not notes:
            return _ok(f"No notes found for paper '{target_id}'.")

        paper_title = notes[0].paper_title
        paper = ctx.ws.papers.get(target_id)
        year = paper.year if paper else ""
        year_str = f" ({year})" if year else ""

        lines = [f"# {paper_title}{year_str}\n"]

        by_type: dict[str, list[ReadingNote]] = defaultdict(list)
        for n in notes:
            by_type[n.note_type].append(n)

        for ntype, heading in _NOTE_TYPE_HEADINGS.items():
            typed_notes = by_type.get(ntype, [])
            if not typed_notes:
                continue
            lines.append(f"\n## {heading}\n")
            for n in typed_notes:
                section_tag = f"[{n.section}] " if n.section != "overall" else ""
                lines.append(f"- {section_tag}{n.content}\n")

        for ntype, typed_notes in by_type.items():
            if ntype not in _NOTE_TYPE_HEADINGS:
                lines.append(f"\n## {ntype}\n")
                for n in typed_notes:
                    section_tag = f"[{n.section}] " if n.section != "overall" else ""
                    lines.append(f"- {section_tag}{n.content}\n")

        md = "".join(lines)
        safe_name = p.filename.replace(" ", "_").replace("/", "_")
        if not safe_name.endswith(".md"):
            safe_name += ".md"
        out_path = ctx.out_dir / safe_name
        out_path.write_text(md, encoding="utf-8")
        ctx.ws.trace.add("agent", "export_notes", f"{len(notes)} notes → {out_path}")
        return _ok(f"{safe_name} written to {out_path} ({len(notes)} notes for '{paper_title}').")

    return [
        Tool[TakeNoteParams, ToolUseCountMetadata](
            name="take_note",
            description=(
                "Record a deep-reading insight or resolved confusion. Notes survive context "
                "compression — use this whenever you explain something important during deep "
                "reading so it can be exported later. Call multiple times as you read."
            ),
            parameters=TakeNoteParams,
            executor=take_note,
        ),
        Tool[ExportNotesParams, ToolUseCountMetadata](
            name="export_notes",
            description=(
                "Export reading notes for ONE paper as an individual markdown file. "
                "You choose a concise, readable filename related to the paper (e.g. "
                "'RLHF_Ziegler2019_精读'). Each paper gets its own file. "
                "IMPORTANT: You MUST get explicit user confirmation via ask_user BEFORE calling "
                "this tool. Never call export_notes without the user saying yes first."
            ),
            parameters=ExportNotesParams,
            executor=export_notes,
        ),
    ]
