"""SuperAcademicAISearch — auto-trace and visualize the lineage of a research field.

Public entry points:
    from superacademic import run, Settings
    result = run("attention is all you need")
"""
from __future__ import annotations

__version__ = "0.1.0"

from .config import Settings
from .models import (
    Paper,
    GraphNode,
    GraphEdge,
    CitationGraph,
    Roadmap,
    FieldReport,
    PipelineResult,
)

__all__ = [
    "__version__",
    "Settings",
    "Paper",
    "GraphNode",
    "GraphEdge",
    "CitationGraph",
    "Roadmap",
    "FieldReport",
    "PipelineResult",
    "run",
]


def run(query: str, **kwargs):
    """Convenience wrapper around the full pipeline. See core.pipeline.run."""
    from .core.pipeline import run as _run

    return _run(query, **kwargs)
