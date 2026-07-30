"""Small text helpers shared across data sources."""
from __future__ import annotations


def short_id(openalex_id: str | None) -> str | None:
    """Normalize an OpenAlex id/URL to its short form, e.g. 'W2626778328'."""
    if not openalex_id:
        return None
    return openalex_id.rstrip("/").rsplit("/", 1)[-1]


def reconstruct_abstract(inverted_index: dict | None) -> str | None:
    """Rebuild plain-text abstract from OpenAlex's abstract_inverted_index."""
    if not inverted_index:
        return None
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions.append((i, word))
    if not positions:
        return None
    positions.sort(key=lambda p: p[0])
    return " ".join(w for _, w in positions)


def arxiv_id_from_doi(doi: str | None) -> str | None:
    """Extract the arXiv id from an arXiv DOI, e.g. '10.48550/arXiv.2306.08543' -> '2306.08543'."""
    if not doi:
        return None
    low = doi.lower()
    marker = "arxiv."
    i = low.find(marker)
    if i == -1:
        return None
    return doi[i + len(marker):].strip().rstrip("/") or None


def normalize_title(title: str | None) -> str:
    """Lowercased alphanumeric-only title, for fuzzy de-duplication."""
    if not title:
        return ""
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in title).split())
