"""Per-run shared state for the research agent.

All Stirrup tools for a single ``saagent run`` close over one RunContext instance,
so tool calls share the same citation graph (Workspace), data sources, engine LLM,
and the result slots that ``emit_result`` finally assembles into a PipelineResult.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from saagent.engine.agents.workspace import Workspace
from saagent.engine.config import Settings
from saagent.engine.llm.base import LLMClient as EngineLLM
from saagent.engine.models import CitationGraph, FieldReport, PipelineResult, Roadmap
from saagent.engine.sources.arxiv import ArxivSource
from saagent.engine.sources.openalex import OpenAlexSource
from saagent.engine.store.cache import Cache


@dataclass
class ReadingNote:
    """A single deep-reading insight recorded by the agent via take_note."""

    paper_id: str
    paper_title: str
    section: str  # e.g. "method", "abstract", "overall"
    content: str
    note_type: str  # "insight" / "confusion_resolved" / "key_finding" / "comparison"


@dataclass
class RunContext:
    """Everything the tools need for one research run."""

    settings: Settings
    cache: Cache
    source: OpenAlexSource
    arxiv: ArxivSource
    llm: EngineLLM  # superacademic engine LLM (sync complete_text/complete_json)
    ws: Workspace
    out_dir: Path

    # materialized citation graph (built once from ws by _ensure_graph, then reused)
    graph: CitationGraph | None = None
    # result slots — populated by tools during the loop, read by emit_result
    founding: list[str] = field(default_factory=list)
    roadmap: Roadmap = field(default_factory=Roadmap)
    report: FieldReport = field(default_factory=FieldReport)
    result_path: str | None = None
    result: "PipelineResult | None" = None  # final PipelineResult, set by emit_result (for CLI summary/export)
    # deep-reading notes — accumulated by take_note, exported by export_notes
    reading_notes: list[ReadingNote] = field(default_factory=list)
    # reference to the Stirrup Agent for runtime toggles (e.g. auto-mode continue-block)
    agent: object | None = None

    def set_auto_mode(self, on: bool) -> None:
        if self.agent is not None:
            try:
                self.agent._block_successive_assistant_messages = on  # noqa: SLF001
            except Exception:  # noqa: BLE001
                pass

    def set_research_mode(self, on: bool) -> None:
        """Toggle research mode: enables/disables auto-continue between steps."""
        self.set_auto_mode(on)

    async def aclose(self) -> None:
        try:
            await self.source.aclose()
        except Exception:
            pass
        try:
            await self.arxiv.aclose()
        except Exception:
            pass
        try:
            self.cache.close()
        except Exception:
            pass


def build_context(
    query: str,
    *,
    out_dir: str | Path,
    model: str | None = None,
    max_nodes: int | None = None,
    max_depth: int | None = None,
    cache_path: str | None = None,
    on_event=None,
) -> RunContext:
    """Construct settings + sources + engine LLM + workspace for a run.

    Note: ``Settings.from_env`` also loads SuperAcademicAISearch/.env into os.environ,
    which is how the Stirrup AnthropicMessagesClient later picks up ANTHROPIC_* config.
    """
    from saagent.engine.llm import build_llm

    overrides: dict = {"llm_model": model}
    if max_nodes is not None:
        overrides["max_nodes"] = max_nodes
    if max_depth is not None:
        overrides["max_depth"] = max_depth
    if cache_path is not None:
        overrides["cache_path"] = cache_path

    s = Settings.from_env(**overrides)
    cache = Cache(s.cache_path, enabled=s.use_cache)
    llm = build_llm(s)
    source = OpenAlexSource(s, cache)
    arxiv = ArxivSource(s)
    ws = Workspace(query, s, on_event=on_event)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    return RunContext(
        settings=s, cache=cache, source=source, arxiv=arxiv, llm=llm, ws=ws, out_dir=out
    )
