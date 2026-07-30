#!/usr/bin/env python3
"""
Build a single self-contained offline HTML for the Newspaper edition.

Inlines everything so the resulting file needs no network:
  - style.css        as <style>
  - vis-network JS   as <script>   (fetched once from jsdelivr; cached in _cache/)
  - shared/helpers.js as <script>
  - result.json      as window.__SAAS_PRELOAD_DATA__
  - fetch shim so loadData('./result.json') returns the preloaded object
  - app.js           as <script>

Output:
  web/variants/_offline/01-newspaper.html   (single file, ~1.6 MB)

Usage:
  # from repo root
  python3 web/variants/build-offline.py

  # override input paths
  python3 web/variants/build-offline.py --data path/to/result.json --out out.html
"""
from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from pathlib import Path

VIS_URL = "https://cdn.jsdelivr.net/npm/vis-network@9.1.6/dist/vis-network.min.js"


def escape_script(text: str) -> str:
    """Prevent '</script' in inlined content from prematurely closing the tag."""
    return text.replace("</script", "<\\/script")


def fetch_vis(cache_path: Path) -> str:
    if cache_path.is_file() and cache_path.stat().st_size > 100_000:
        return cache_path.read_text(encoding="utf-8")
    print(f"  downloading {VIS_URL} ...")
    with urllib.request.urlopen(VIS_URL, timeout=30) as r:
        data = r.read().decode("utf-8")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(data, encoding="utf-8")
    return data


def build(variant_dir: Path, result_json_path: Path, helpers_path: Path,
          vis_js: str, out_path: Path) -> int:
    html = (variant_dir / "index.html").read_text(encoding="utf-8")
    css = (variant_dir / "style.css").read_text(encoding="utf-8")
    app_js = (variant_dir / "app.js").read_text(encoding="utf-8")
    helpers_js = helpers_path.read_text(encoding="utf-8")
    result_json = result_json_path.read_text(encoding="utf-8")

    # Strip external stylesheet + Google Fonts (system font fallback is fine offline)
    html = re.sub(
        r'<link\s+rel="stylesheet"\s+href="\./style\.css"\s*/?>', '', html)
    html = re.sub(r'<link\s+rel="preconnect"[^>]*>\s*', '', html)
    html = re.sub(
        r'<link\s+rel="stylesheet"\s+href="https://fonts\.googleapis\.com[^"]+"[^>]*>',
        '', html)

    # Strip external scripts (CDN vis-network, shared helpers, app.js)
    html = re.sub(
        r'<script\s+src="https://unpkg\.com/vis-network[^"]*"[^>]*></script>', '', html)
    html = re.sub(
        r'<script\s+src="\.\./shared/helpers\.js"[^>]*></script>', '', html)
    html = re.sub(r'<script\s+src="\./app\.js"[^>]*></script>', '', html)

    # Inline css at end of <head>
    html = html.replace('</head>', f'<style>\n{css}\n</style>\n</head>', 1)

    # Injections before </body>
    inject = [
        f"<script>window.__SAAS_PRELOAD_DATA__ = {result_json};</script>",
        "<script>(function(){"
        "var _f=window.fetch;"
        "window.fetch=function(u,o){"
        "  if(typeof u==='string' && u.indexOf('result.json')>=0){"
        "    return Promise.resolve({ok:true,status:200,json:function(){"
        "      return Promise.resolve(window.__SAAS_PRELOAD_DATA__);}});"
        "  }"
        "  return _f?_f.call(this,u,o):Promise.reject(new Error('offline'));"
        "};"
        "})();</script>",
        f"<script>{escape_script(vis_js)}</script>",
        f"<script>{escape_script(helpers_js)}</script>",
        f"<script>{escape_script(app_js)}</script>",
    ]
    html = html.replace('</body>', '\n'.join(inject) + '\n</body>', 1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return len(html)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    web_variants = repo_root / "web" / "variants"

    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--data", type=Path,
                        default=web_variants / "shared" / "result.json",
                        help="Path to result.json (default: shared/result.json symlink)")
    parser.add_argument("--out", type=Path,
                        default=web_variants / "_offline" / "01-newspaper.html",
                        help="Output path for the offline HTML")
    parser.add_argument("--variant", type=Path,
                        default=web_variants / "01-newspaper",
                        help="Variant directory containing index.html/style.css/app.js")
    parser.add_argument("--helpers", type=Path,
                        default=web_variants / "shared" / "helpers.js",
                        help="Path to shared helpers.js")
    args = parser.parse_args()

    # Resolve relative symlinks correctly regardless of CWD.
    args.data = args.data.expanduser().resolve() if args.data.is_symlink() or args.data.exists() else args.data
    data_path = args.data
    if not data_path.exists():
        sys.exit(f"[error] data file not found: {args.data}\n"
                 f"  Hint: run `superacademic run \"your query\" --out results/demo` first,\n"
                 f"        then symlink or point --data to that result.json.")

    vis_cache = web_variants / "_cache" / "vis-network.min.js"
    print("Building offline bundle:")
    print(f"  variant : {args.variant}")
    print(f"  data    : {args.data}")
    print(f"  helpers : {args.helpers}")

    vis_js = fetch_vis(vis_cache)
    size = build(args.variant, data_path, args.helpers, vis_js, args.out)

    print(f"\n  → {args.out}  ({size / 1024:.1f} KB)")
    print("Done.  Double-click the file to view offline; no network needed.")


if __name__ == "__main__":
    main()
