"""Shared, mutable workspace the agents read from and write to, plus a trace."""
from __future__ import annotations

from ..models import CitationGraph, GraphEdge, GraphNode, Paper


def _has_title(p: Paper) -> bool:
    t = (p.title or "").strip()
    return bool(p.id) and bool(t) and t.lower() != "(untitled)"


class Trace:
    """Append-only event log — the proof of agentic behavior (for demo/inspection)."""

    def __init__(self, on_event=None) -> None:
        self.events: list[dict] = []
        self._on_event = on_event  # optional live callback(event_dict)

    def add(self, agent: str, kind: str, content) -> None:
        ev = {"i": len(self.events), "agent": agent, "type": kind, "content": content}
        self.events.append(ev)
        if self._on_event is not None:
            try:
                self._on_event(ev)
            except Exception:
                pass

    def dump(self) -> list[dict]:
        return self.events


class Workspace:
    def __init__(self, query: str, settings, on_event=None) -> None:
        self.query = query
        self.settings = settings
        self.papers: dict[str, Paper] = {}
        self.depth: dict[str, int] = {}
        self.seeds: list[str] = []
        self.expanded_fwd: set[str] = set()  # nodes whose citers we've fetched
        self.expanded_bwd: set[str] = set()  # nodes whose references we've pulled
        self.link_attempted: set[str] = set()  # nodes link_frontier already tried (success or not)
        self.trace = Trace(on_event=on_event)

    # -- mutation ---------------------------------------------------------
    def add_paper(self, p: Paper, depth: int) -> bool:
        if not _has_title(p):
            return False
        if p.id in self.papers:
            return False
        # Collection cap is intentionally larger than max_nodes (the final target):
        # otherwise early most-cited expansion fills every slot and the late-fetched
        # frontier can't get in. Relevance pruning trims to the on-topic final graph.
        cap = self.settings.max_collect or self.settings.max_nodes * 4
        if len(self.papers) >= cap:
            return False
        self.papers[p.id] = p
        self.depth[p.id] = depth
        return True

    def add_seed(self, p: Paper) -> None:
        if self.add_paper(p, 0):
            self.seeds.append(p.id)

    # -- views for the agent ---------------------------------------------
    def frontier(self, k: int = 8) -> list[Paper]:
        """High-citation nodes not yet expanded forward — best expansion targets."""
        cand = [p for pid, p in self.papers.items() if pid not in self.expanded_fwd]
        return sorted(cand, key=lambda p: p.citation_count, reverse=True)[:k]

    def degree(self) -> dict[str, int]:
        """In+out citation-edge degree of each paper, counting only edges to other
        papers currently in the graph (mirrors the edges to_graph() would emit)."""
        deg: dict[str, int] = {pid: 0 for pid in self.papers}
        node_ids = set(self.papers)
        for pid, p in self.papers.items():
            for r in p.referenced_works:
                if r in node_ids and r != pid:
                    deg[pid] += 1
                    deg[r] += 1
        return deg

    def summary(self, k: int = 8) -> str:
        n = len(self.papers)
        top = sorted(self.papers.values(), key=lambda p: p.citation_count, reverse=True)[:k]
        lines = [f"Graph now has {n}/{self.settings.max_nodes} papers."]
        deg = self.degree()
        isolated = [pid for pid, d in deg.items() if d == 0]
        if isolated:
            # referenced_works is only ever populated by OpenAlex (arXiv-sourced Paper
            # objects never carry it) — so whether THAT field is empty, not in-graph
            # degree, is what tells us a paper is genuinely missing reference data vs.
            # just not-yet-expanded (its known references simply aren't in this graph).
            need_fulltext = sorted(
                (
                    pid for pid in isolated
                    if not self.papers[pid].referenced_works and self.papers[pid].source_ids.get("arxiv")
                ),
                key=lambda pid: self.papers[pid].citation_count,
                reverse=True,
            )
            need_expand = sorted(
                (pid for pid in isolated if self.papers[pid].referenced_works and pid not in self.expanded_bwd),
                key=lambda pid: self.papers[pid].citation_count,
                reverse=True,
            )
            lines.append(f"⚠ {len(isolated)}/{n} papers have ZERO citation edges (disconnected from the graph)")
            if need_fulltext:
                shown = ", ".join(need_fulltext[:20])
                more = f" (+{len(need_fulltext) - 20} more)" if len(need_fulltext) > 20 else ""
                lines.append(
                    f"  — {len(need_fulltext)} have NO reference data at all (OpenAlex never indexed "
                    f"their refs) but DO have arXiv full text: call link_frontier with ALL these ids "
                    f"at once to extract+wire them in: {shown}{more}"
                )
            if need_expand:
                shown = ", ".join(need_expand[:20])
                more = f" (+{len(need_expand) - 20} more)" if len(need_expand) > 20 else ""
                lines.append(
                    f"  — {len(need_expand)} already HAVE reference data (from OpenAlex) but haven't "
                    f"been expand_backward'd yet — their cited papers just aren't in this graph yet, "
                    f"use expand_backward (not link_frontier, that would waste a PDF read re-deriving "
                    f"what OpenAlex already gave us): {shown}{more}"
                )
        lines.append("Top by citations:")
        for p in top:
            mark = "" if p.id in self.expanded_fwd else "  [not expanded]"
            lines.append(f"  {p.id} | {p.year} | cites={p.citation_count} | {p.title[:60]}{mark}")
        return "\n".join(lines)

    # -- output -----------------------------------------------------------
    def to_graph(self) -> CitationGraph:
        node_ids = set(self.papers)
        edges: list[GraphEdge] = []
        seen: set[tuple[str, str]] = set()
        for pid, p in self.papers.items():
            for r in p.referenced_works:
                if r in node_ids and (pid, r) not in seen:
                    edges.append(GraphEdge(source=pid, target=r, type="cites"))
                    seen.add((pid, r))
        nodes = [
            GraphNode(
                paper_id=p.id,
                title=p.title,
                year=p.year,
                citation_count=p.citation_count,
                depth=self.depth.get(p.id, 0),
            )
            for p in self.papers.values()
        ]
        return CitationGraph(
            query=self.query, seeds=self.seeds, nodes=nodes, edges=edges, papers=dict(self.papers)
        )
