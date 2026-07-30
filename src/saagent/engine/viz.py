"""Step C6: render results to a static PNG (matplotlib) and interactive HTML.

The interactive HTML re-uses the annotated-edition front-end living in `web/`:
we read `web/index.html`, `web/app.css`, and `web/app.js`, then inline the
stylesheet, the script, and the full PipelineResult as `window.__SAAS_DATA__`
so the output is a single self-contained file that needs no server.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .models import PipelineResult

ROLE_COLORS = {
    "founding": "#e6194B",
    "breakthrough": "#f58231",
    "branch": "#4363d8",
    "improvement": "#3cb44b",
    "survey": "#911eb4",
    "normal": "#9aa0a6",
    None: "#9aa0a6",
}


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _short(title: str, n: int = 28) -> str:
    title = title or ""
    return title if len(title) <= n else title[: n - 1] + "…"


# --------------------------------------------------------------------------- #
# Static PNG (matplotlib)                                                      #
# --------------------------------------------------------------------------- #
def to_png(result: PipelineResult, path: str, label_top: int = 12) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import networkx as nx

    g = nx.DiGraph()
    for n in result.graph.nodes:
        g.add_node(n.paper_id)
    for e in result.graph.edges:
        if e.source in g and e.target in g:
            g.add_edge(e.source, e.target)
    if g.number_of_nodes() == 0:
        return

    nodes = {n.paper_id: n for n in result.graph.nodes}
    pr = {pid: n.metrics.get("pagerank", 0.0) for pid, n in nodes.items()}
    prmax = max(pr.values()) or 1.0
    sizes = [120 + 2600 * (pr[pid] / prmax) for pid in g.nodes]
    colors = [ROLE_COLORS.get(nodes[pid].role, ROLE_COLORS["normal"]) for pid in g.nodes]

    try:
        pos = nx.kamada_kawai_layout(g) if g.number_of_nodes() <= 120 else nx.spring_layout(
            g, seed=42, k=0.6
        )
    except Exception:
        pos = nx.spring_layout(g, seed=42, k=0.6)

    fig, ax = plt.subplots(figsize=(16, 11))
    nx.draw_networkx_edges(g, pos, ax=ax, edge_color="#d0d0d0", arrows=True, arrowsize=7, width=0.6)
    nx.draw_networkx_nodes(g, pos, ax=ax, node_size=sizes, node_color=colors, alpha=0.9,
                           linewidths=0.5, edgecolors="#333")

    top_ids = sorted(g.nodes, key=lambda p: pr[p], reverse=True)[:label_top]
    labels = {pid: _short(nodes[pid].title) for pid in top_ids}
    nx.draw_networkx_labels(g, pos, labels=labels, ax=ax, font_size=8)

    handles = [
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=c, markersize=10, label=r)
        for r, c in ROLE_COLORS.items()
        if r and r != "normal"
    ]
    ax.legend(handles=handles, loc="lower left", fontsize=9, title="role")
    ax.set_title(
        f"Citation network: {result.query}  "
        f"({len(result.graph.nodes)} papers, node size ∝ PageRank)",
        fontsize=13,
    )
    ax.axis("off")
    _ensure_parent(path)
    fig.tight_layout()
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Interactive HTML — Annotated Edition, single self-contained file             #
# --------------------------------------------------------------------------- #

# The web/ directory is vendored inside this engine package (src/saagent/engine/web/).
_WEB_DIR = Path(__file__).resolve().parent / "web"


def to_html(result: PipelineResult, path: str) -> None:
    """Render the DEFAULT view: the Newspaper edition, as one self-contained HTML file.

    Inlines web/variants/01-newspaper (index.html/style.css/app.js) + shared/helpers.js
    and preloads the PipelineResult (with a fetch shim so loadData('./result.json')
    returns it). vis-network is left as a CDN reference (loaded only when the reader
    expands the network appendix). Falls back to the annotated edition if the newspaper
    variant is missing.
    """
    variant = _WEB_DIR / "variants" / "01-newspaper"
    helpers = _WEB_DIR / "variants" / "shared" / "helpers.js"
    try:
        html = (variant / "index.html").read_text(encoding="utf-8")
        css = (variant / "style.css").read_text(encoding="utf-8")
        app_js = (variant / "app.js").read_text(encoding="utf-8")
        helpers_js = helpers.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _to_html_annotated(result, path)

    def _esc(t: str) -> str:  # keep inlined </script> from closing the tag early
        return t.replace("</script", "<\\/script")

    result_json = json.dumps(result.model_dump(), ensure_ascii=False)
    # inline the stylesheet; drop the external helpers.js / app.js tags (re-injected inline)
    html = re.sub(r'<link\s+rel="stylesheet"\s+href="\./style\.css"\s*/?>',
                  f"<style>\n{css}\n</style>", html, count=1)
    html = re.sub(r'<script\s+src="\.\./shared/helpers\.js"[^>]*></script>', "", html)
    html = re.sub(r'<script\s+src="\./app\.js"[^>]*></script>', "", html)

    inject = "\n".join([
        f"<script>window.__SAAS_PRELOAD_DATA__ = {_esc(result_json)};</script>",
        "<script>(function(){var _f=window.fetch;window.fetch=function(u,o){"
        "if(typeof u==='string'&&u.indexOf('result.json')>=0){return Promise.resolve("
        "{ok:true,status:200,json:function(){return Promise.resolve(window.__SAAS_PRELOAD_DATA__);}});}"
        "return _f?_f.call(this,u,o):Promise.reject(new Error('offline'));};})();</script>",
        f"<script>\n{_esc(helpers_js)}\n</script>",
        f"<script>\n{_esc(app_js)}\n</script>",
    ])
    html = html.replace("</body>", inject + "\n</body>", 1)

    _ensure_parent(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def _to_html_annotated(result: PipelineResult, path: str) -> None:
    """Annotated-edition renderer (previous default; kept as a fallback / option)."""
    try:
        template = (_WEB_DIR / "index.html").read_text(encoding="utf-8")
        css = (_WEB_DIR / "app.css").read_text(encoding="utf-8")
        js = (_WEB_DIR / "app.js").read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise RuntimeError(
            f"Annotated-edition templates missing in {_WEB_DIR}. Reinstall the repo "
            "with the `web/` directory included."
        ) from e

    data_json = json.dumps(result.model_dump(), ensure_ascii=False)
    # JSON-in-script needs </script tags neutralised so the parser doesn't bail.
    safe_data = data_json.replace("</", "<\\/")
    data_block = f'<script>window.__SAAS_DATA__ = {safe_data};</script>'

    html = template
    # Replace the external stylesheet link with an inline <style>.
    html = re.sub(
        r'<link[^>]+href="\./app\.css"[^>]*>',
        lambda _m: f"<style>\n{css}\n</style>",
        html,
        count=1,
    )
    # Replace the external script tag with the inline payload.
    html = re.sub(
        r'<script[^>]+src="\./app\.js"[^>]*></script>',
        lambda _m: f"{data_block}\n<script>\n{js}\n</script>",
        html,
        count=1,
    )

    _ensure_parent(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
