"""arXiv source: search the freshest preprints (no citations needed) + deep-read PDFs.

This is the answer to "how do we reach the bleeding edge?" — arXiv has papers the day
they're posted, long before citations accrue or OpenAlex indexes them. For brand-new
directions (no survey, no citations), arXiv search-by-date + full-text reading is the
only signal. PDFs are parsed with PyMuPDF (fitz).
"""
from __future__ import annotations

import asyncio
import datetime
import re
import xml.etree.ElementTree as ET

import httpx

from ..models import Paper
from ..util import RateLimiter

_NS = {"atom": "http://www.w3.org/2005/Atom"}
_API = "https://export.arxiv.org/api/query"

# Canonical section buckets we care about, and the header aliases that map to each.
_SECTION_ALIASES = {
    "abstract": ("abstract",),
    "introduction": ("introduction", "overview"),
    "related_work": ("related work", "related works", "background", "prior work", "preliminaries"),
    "method": ("method", "methods", "methodology", "approach", "model", "architecture", "our model"),
    "experiments": ("experiment", "experiments", "evaluation", "results", "experimental results"),
    "conclusion": ("conclusion", "conclusions", "discussion", "future work", "limitations"),
    "references": ("references", "bibliography"),
}
# a heading line = optional numbering ("3", "3.", "III") + one of the alias phrases, alone-ish on the line
_HEADING_RE = re.compile(
    r"(?im)^[ \t]*(?:\d{1,2}(?:\.\d{1,2})*\.?|[ivxIVX]{1,5}\.)?[ \t]*"
    r"(abstract|introduction|overview|related works?|background|prior work|preliminaries|"
    r"methodology|methods?|approach|architecture|our model|model|"
    r"experimental results|experiments?|evaluation|results?|"
    r"conclusions?|discussion|future work|limitations|references|bibliography)"
    r"[ \t]*:?[ \t]*$"
)


def _canonical_section(heading: str) -> str | None:
    h = heading.strip().lower()
    for canon, aliases in _SECTION_ALIASES.items():
        if h in aliases:
            return canon
    return None


def split_sections(text: str) -> dict[str, str]:
    """Best-effort split of a paper's plain text into canonical sections by heading
    lines. Returns {section_name: body}. Robust to PDF noise: if no headings are
    found it returns {} and callers fall back to full text."""
    if not text:
        return {}
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return {}
    out: dict[str, str] = {}
    for i, m in enumerate(matches):
        canon = _canonical_section(m.group(1))
        if not canon:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body and (canon not in out or len(body) > len(out[canon])):
            out[canon] = body  # keep the richest occurrence of each section
    return out


def _arxiv_id(raw: str) -> str:
    # http://arxiv.org/abs/2606.30611v1 -> 2606.30611
    tail = raw.rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"v\d+$", "", tail)


class ArxivSource:
    name = "arxiv"

    def __init__(self, settings=None):
        self._client = httpx.AsyncClient(
            timeout=60.0, headers={"User-Agent": "SuperAcademicAISearch/0.1"}
        )
        # arXiv asks for <= 1 request / 3s; be gentle (~1 / 3.3s) to avoid 503s.
        self._limiter = RateLimiter(rate_per_sec=0.3)

    async def _fetch(self, url: str, params: dict | None = None,
                     follow_redirects: bool = False, timeout: float = 20.0):
        """Rate-limited GET with a short retry on 503/429 (arXiv throttles bursts).

        Fails FAST (2 attempts, brief backoff): when arXiv is throttling us, retrying
        hard just stalls the run — better to fall back to [] quickly (OpenAlex still
        works). The rate limiter is the real fix, spacing calls to avoid the throttle.
        Returns the httpx.Response, or None on give-up. Never raises."""
        for attempt in range(2):
            await self._limiter.acquire()
            try:
                r = await self._client.get(
                    url, params=params, follow_redirects=follow_redirects, timeout=timeout
                )
                if r.status_code in (503, 429):
                    if attempt == 0:
                        await asyncio.sleep(4)
                        continue
                    return None
                r.raise_for_status()
                return r
            except httpx.HTTPError:
                if attempt == 0:
                    await asyncio.sleep(2)
                    continue
                return None
        return None

    async def search(
        self, query: str, max_results: int = 10, sort: str = "submittedDate"
    ) -> list[Paper]:
        """Search arXiv. sort='submittedDate' (newest first) or 'relevance'.

        Multi-word queries are phrase-quoted: arXiv otherwise splits on spaces and
        OR-joins the terms (e.g. "on-policy distillation" -> on-policy OR distillation),
        which floods results with off-topic noise.
        """
        q = query.strip()
        if " " in q and not (q.startswith('"') and q.endswith('"')):
            q = f'"{q}"'
        params = {
            "search_query": f"all:{q}",
            "start": 0,
            "max_results": max_results,
            "sortBy": sort,
            "sortOrder": "descending",
        }
        r = await self._fetch(_API, params=params)
        if r is None:
            return []
        try:
            root = ET.fromstring(r.text)
        except ET.ParseError:
            return []
        papers: list[Paper] = []
        for e in root.findall("atom:entry", _NS):
            aid = _arxiv_id(e.findtext("atom:id", default="", namespaces=_NS))
            title = " ".join((e.findtext("atom:title", "", _NS) or "").split())
            summary = " ".join((e.findtext("atom:summary", "", _NS) or "").split())
            pub = e.findtext("atom:published", "", _NS) or ""
            year = int(pub[:4]) if pub[:4].isdigit() else None
            authors = [
                a.findtext("atom:name", "", _NS)
                for a in e.findall("atom:author", _NS)
            ]
            if not aid or not title:
                continue
            papers.append(
                Paper(
                    id=f"arxiv:{aid}",
                    title=title,
                    abstract=summary or None,
                    year=year,
                    authors=[a for a in authors if a],
                    venue="arXiv",
                    url=f"https://arxiv.org/abs/{aid}",
                    arxiv_url=f"https://arxiv.org/abs/{aid}",
                    pdf_url=f"https://arxiv.org/pdf/{aid}",
                    source_ids={"arxiv": aid},
                )
            )
        return papers

    async def fulltext(
        self, arxiv_id: str, max_pages: int | None = None, max_chars: int = 60000
    ) -> str:
        """Download the PDF and extract text. Extracts the WHOLE document by default
        (max_pages=None) so late sections — Related Work, References — are captured;
        first-N-pages truncation used to drop exactly the lineage signal we need.
        Empty string on failure."""
        aid = arxiv_id.split(":")[-1]
        url = f"https://arxiv.org/pdf/{aid}"
        r = await self._fetch(url, follow_redirects=True, timeout=60.0)  # PDFs are larger
        if r is None:
            return ""
        content = r.content

        def _parse(data: bytes) -> str:
            import fitz  # PyMuPDF

            try:
                doc = fitz.open(stream=data, filetype="pdf")
            except Exception:
                return ""
            pages = list(doc) if max_pages is None else list(doc)[:max_pages]
            parts = [page.get_text() for page in pages]
            doc.close()
            return "\n".join(parts)

        text = await asyncio.to_thread(_parse, content)
        return text[:max_chars].strip()

    async def fulltext_sections(self, arxiv_id: str, max_chars: int = 60000) -> dict:
        """Deep-read helper: full text + section-split (abstract / introduction /
        related_work / method / experiments / conclusion / references). Grounds the
        agent's reading and lets link-back target the related-work + references."""
        text = await self.fulltext(arxiv_id, max_pages=None, max_chars=max_chars)
        return {"full_text": text, "sections": split_sections(text)}

    async def aclose(self) -> None:
        await self._client.aclose()
