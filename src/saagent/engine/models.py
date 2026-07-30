"""Pydantic data models shared across the pipeline."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PaperRole = Literal[
    "founding",  # 奠基/开创
    "breakthrough",  # 范式突破
    "improvement",  # 关键改进
    "branch",  # 分支开创
    "survey",  # 集大成综述
    "normal",
]

EdgeType = Literal["cites", "inspires", "improves", "contrasts"]


class Paper(BaseModel):
    """A single work, normalized across data sources."""

    id: str  # internal id (OpenAlex short id, e.g. "W2626778328")
    title: str
    doi: str | None = None
    abstract: str | None = None
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    venue: str | None = None
    citation_count: int = 0
    referenced_works: list[str] = Field(default_factory=list)  # outgoing references (ids)
    url: str | None = None  # primary landing page (OpenAlex / arXiv abs)
    arxiv_url: str | None = None  # https://arxiv.org/abs/<id> when available (else None)
    pdf_url: str | None = None  # direct PDF when available (arXiv / open-access)
    source_ids: dict = Field(default_factory=dict)  # {openalex, arxiv, ...}


class GraphNode(BaseModel):
    paper_id: str
    title: str
    year: int | None = None
    citation_count: int = 0
    depth: int = 0  # BFS distance from the nearest seed
    role: PaperRole | None = None
    metrics: dict = Field(default_factory=dict)  # pagerank, betweenness, ...
    ai_summary: str | None = None


class GraphEdge(BaseModel):
    # Citation edge convention: source CITES target (source is newer, target is older).
    source: str
    target: str
    type: EdgeType = "cites"
    weight: float | None = None


class CitationGraph(BaseModel):
    query: str = ""
    seeds: list[str] = Field(default_factory=list)
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    papers: dict[str, Paper] = Field(default_factory=dict)

    def node(self, paper_id: str) -> GraphNode | None:
        for n in self.nodes:
            if n.paper_id == paper_id:
                return n
        return None


class RoadmapNode(BaseModel):
    paper_id: str
    title: str
    year: int | None = None
    role: PaperRole = "normal"
    stage: str | None = None
    contribution: str | None = None


class RoadmapEdge(BaseModel):
    source: str  # earlier / influencing
    target: str  # later / influenced
    relation: str = "leads_to"


class Roadmap(BaseModel):
    nodes: list[RoadmapNode] = Field(default_factory=list)
    edges: list[RoadmapEdge] = Field(default_factory=list)


class Stage(BaseModel):
    name: str
    period: str | None = None
    summary: str = ""
    papers: list[str] = Field(default_factory=list)
    headline: str | None = None  # 1-line stage "epigraph"; populated by LLM analyzer


class SeedAnalysis(BaseModel):
    """Analysis of the paper the user actually asked about (the seed).

    Distinct from `founding_papers` — the seed is the user's entry point, which
    may be the field's founding, a mid-line breakthrough, a branch, or a very
    recent frontier paper. This block explains what THIS specific paper is and
    how it relates to the field's main line.
    """
    paper_id: str
    title: str
    year: int | None = None
    role_in_field: PaperRole | None = None       # reuse the existing role enum
    on_main_line: bool = False                    # is the seed on the roadmap main_line?
    stage_name: str | None = None                 # which stage does it fall in
    summary: str = ""                             # 1-2 plain-language sentences: what this paper is/does
    relation_to_main_line: str = ""               # 2-3 sentences: how it sits on the field's arc


class FieldReport(BaseModel):
    query: str = ""
    founding_papers: list[str] = Field(default_factory=list)
    stages: list[Stage] = Field(default_factory=list)
    main_line: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    reading_path: list[str] = Field(default_factory=list)
    must_read: list[str] = Field(default_factory=list)
    must_read_reasons: dict[str, str] = Field(default_factory=dict)  # paper_id -> one-line reason
    narrative: str = ""
    cover_title: str | None = None  # model-composed cover title (academic + literary); falls back to the raw query
    cover_blurb: str | None = None  # one-sentence epigraph shown under the field title
    # --- newcomer guide (Pro/deep report; teaches someone who knows nothing) ---
    tldr: str | None = None  # plain-language "what is this field" for a total beginner
    core_idea: str | None = None  # the single key insight, in plain terms
    prerequisites: list[str] = Field(default_factory=list)  # what to know first
    glossary: dict[str, str] = Field(default_factory=dict)  # term -> plain-language definition
    getting_started: list[str] = Field(default_factory=list)  # concrete first steps to enter the field
    seed_paper: SeedAnalysis | None = None  # analysis of the paper the user asked about, in the context of this field
    degraded: bool = False  # True when LLM failed and report fell back to heuristic-only


class PipelineResult(BaseModel):
    query: str
    seeds: list[str] = Field(default_factory=list)
    graph: CitationGraph
    founding: list[str] = Field(default_factory=list)
    roadmap: Roadmap = Field(default_factory=Roadmap)
    report: FieldReport = Field(default_factory=FieldReport)
    llm_used: bool = False
    agentic: bool = False
    trace: list = Field(default_factory=list)  # agent decision/verification log (demo)
    i18n: dict[str, dict] = Field(default_factory=dict)  # locale -> translated fields; e.g. {"zh": {...}}
