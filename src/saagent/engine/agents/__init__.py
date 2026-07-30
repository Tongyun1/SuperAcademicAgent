"""Agentic layer: graph-guided tool-using agents with adversarial verification.

Combines five patterns into one orchestration:
  1. graph-guided autonomous exploration  (ScoutAgent + graph signals)
  2. adversarial verification             (verify.py, majority vote)
  3. tool use                             (runtime.Tool + ReAct loop)
  4. multi-agent roles                    (scout / founding / curator / synth)
  5. self-correction loop                 (orchestrator re-queries on failure)
"""
from .runtime import Agent, Tool, AgentResult
from .workspace import Workspace, Trace
from .orchestrator import run_agentic

__all__ = ["Agent", "Tool", "AgentResult", "Workspace", "Trace", "run_agentic"]
