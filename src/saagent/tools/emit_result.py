"""The finish tool: assemble a contract-compatible PipelineResult and write result.json.

This replaces Stirrup's default finish tool. Calling it ends the agent loop AND
produces the deliverable the frontend consumes (result.json == PipelineResult.model_dump()).
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from stirrup import Tool, ToolResult, ToolUseCountMetadata
from saagent.engine.models import PipelineResult

from ..context import RunContext
from .analysis import _ensure_graph


class EmitParams(BaseModel):
    reason: str = Field(
        description="Short explanation of why the research task is complete (or why it cannot proceed further)."
    )


def build_emit_result_tool(ctx: RunContext) -> Tool:
    def emit_result(p: EmitParams) -> ToolResult[ToolUseCountMetadata]:
        ctx.set_research_mode(False)
        # reuse the same materialized graph the analysis tools built (dedup + metrics + relevance)
        graph = _ensure_graph(ctx)
        if ctx.founding:
            fset = set(ctx.founding)
            for node in graph.nodes:
                if node.paper_id in fset:
                    node.role = "founding"
        ctx.ws.trace.add("agent", "finish", p.reason)

        result = PipelineResult(
            query=ctx.ws.query,
            seeds=list(ctx.ws.seeds),
            graph=graph,
            founding=list(ctx.founding),
            roadmap=ctx.roadmap,
            report=ctx.report,
            llm_used=getattr(ctx.llm, "available", False),
            agentic=True,
            trace=ctx.ws.trace.dump(),
        )

        ctx.result = result  # hand to the CLI for full export + run summary
        out_path = ctx.out_dir / "result.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)  # out_dir may not exist yet
        out_path.write_text(
            json.dumps(result.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        ctx.result_path = str(out_path)

        n, m = len(graph.nodes), len(graph.edges)
        hint = '💡 你可以继续说"精读 founding paper"或指定论文的某个章节来深入研读，完成后说"沉淀"导出笔记。'
        msg = (
            f"result.json written to {out_path} ({n} nodes, {m} edges; "
            f"founding={len(ctx.founding)}, roadmap={len(ctx.roadmap.nodes)} nodes). "
            f"Reason: {p.reason}\n{hint}"
        )
        return ToolResult(content=msg, metadata=ToolUseCountMetadata(), success=True)

    return Tool[EmitParams, ToolUseCountMetadata](
        name="emit_result",
        description=(
            "Finish the task: assemble the citation network + findings into result.json "
            "(the deliverable) and end the run. Call this ONLY when you have at least a "
            "seed-anchored citation graph, and any founding/roadmap/report you intend to produce."
        ),
        parameters=EmitParams,
        executor=emit_result,
    )
