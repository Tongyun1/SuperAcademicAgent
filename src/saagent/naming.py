"""Output-directory naming: turn a research query into a filesystem-safe,
human-readable directory name and resolve the default output root.

The old default (~/.saagent/sessions/<timestamp>/) was a hidden dot-directory
invisible to Finder/Spotlight, and timestamp names said nothing about the
research inside. The new default root is ~/saagent-results (non-hidden),
overridable via the SAAS_OUT_DIR env var, and the directory itself is named
after the research direction (query slug).
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

# Non-hidden default root for research outputs. Must stay OUTSIDE ~/.saagent
# (a hidden dot-directory) so results are visible in Finder / Spotlight.
_DEFAULT_ROOT = Path.home() / "saagent-results"

# Keep slugs short enough to be path-safe and glanceable; 48 chars covers
# typical research directions (Chinese chars count as one each).
_MAX_SLUG_LEN = 48


def slugify_query(query: str, max_len: int = _MAX_SLUG_LEN) -> str:
    """Turn a research query into a filesystem-safe directory name.

    - CJK characters pass through untouched (macOS APFS handles them natively;
      py3 re's ``\\w`` is Unicode-aware so ASCII + CJK + digits all survive)
    - ``.`` and ``-`` pass through too (DOI / arXiv IDs and hyphenated titles
      stay readable: "10.48550/arXiv.1706.03762" -> "10.48550-arxiv.1706.03762")
    - ASCII letters lowercased; runs of anything else collapse to a single '-'
    - truncated at max_len Python characters (never mid-codepoint)
    - empty / all-symbols input falls back to "research-<YYYYmmdd_HHMMSS>"
    """
    s = query.strip()
    s = re.sub(r"[^\w一-鿿.-]+", "-", s, flags=re.UNICODE)
    s = re.sub(r"-{2,}", "-", s).strip("-").lower()
    s = s[:max_len].rstrip("-")
    if not s:
        s = f"research-{datetime.now():%Y%m%d_%H%M%S}"
    return s


def unique_dir(base: Path) -> Path:
    """Return ``base``, or ``base-2`` / ``base-3`` ... when the name is taken.

    Never overwrites: re-running the same research direction gets its own
    directory instead of silently clobbering the previous run.
    """
    if not base.exists():
        return base
    for i in range(2, 1000):
        candidate = base.with_name(f"{base.name}-{i}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"too many colliding output dirs for {base}")


def default_out_dir(query: str, root: str | Path | None = None) -> str:
    """Resolve the default output directory for a research query.

    Root precedence: explicit ``root`` arg > ``SAAS_OUT_DIR`` env var >
    ``~/saagent-results``. Does NOT create the directory — callers that write
    into it do that (mirrors how an explicit ``--out`` is handled today).
    """
    if root is None:
        root = Path(os.getenv("SAAS_OUT_DIR", "") or _DEFAULT_ROOT)
    base = Path(root).expanduser() / slugify_query(query or "research")
    return str(unique_dir(base))
