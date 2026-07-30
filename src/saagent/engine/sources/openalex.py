"""OpenAlex data source (https://docs.openalex.org).

Confirmed endpoints used:
  - search:   GET /works?search=<q>&per-page=<n>
  - batch:    GET /works?filter=ids.openalex:W1|W2|...   (<=50 ids per call)
  - citing:   GET /works?filter=cites:<Wid>&sort=cited_by_count:desc
  - one work: GET /works/<id|doi-url>
referenced_works (outgoing references) ships inside each work object.
"""
from __future__ import annotations

import asyncio
import re

import httpx

from ..config import Settings
from ..models import Paper
from ..store import Cache
from ..util import RateLimiter, arxiv_id_from_doi, reconstruct_abstract, short_id

_SELECT = ",".join(
    [
        "id",
        "doi",
        "display_name",
        "publication_year",
        "cited_by_count",
        "referenced_works",
        "authorships",
        "primary_location",
        "locations",
        "abstract_inverted_index",
    ]
)

_ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", re.I)


def _arxiv_from_locations(w: dict) -> str | None:
    locs = [w.get("primary_location") or {}] + (w.get("locations") or [])
    for loc in locs:
        for key in ("landing_page_url", "pdf_url"):
            m = _ARXIV_URL_RE.search(loc.get(key) or "")
            if m:
                return m.group(1)
    return None


class OpenAlexSource:
    name = "openalex"

    def __init__(self, settings: Settings, cache: Cache | None = None):
        self.s = settings
        self.cache = cache
        self._limiter = RateLimiter(settings.rate_per_sec)
        self._sem = asyncio.Semaphore(settings.max_concurrency)
        params = {}
        if settings.mailto:
            params["mailto"] = settings.mailto
        # free API key -> uninterrupted access (OpenAlex rate-limits anonymous search under load)
        if getattr(settings, "openalex_api_key", None):
            params["api_key"] = settings.openalex_api_key
        self._client = httpx.AsyncClient(
            base_url=settings.openalex_base,
            timeout=settings.request_timeout,
            params=params,
            headers={"User-Agent": f"SuperAcademicAISearch (mailto:{settings.mailto or 'n/a'})"},
        )

    # ---- low level -------------------------------------------------------
    async def _get(self, path: str, params: dict | None = None) -> dict | None:
        async with self._sem:
            await self._limiter.acquire()
            for attempt in range(3):
                try:
                    r = await self._client.get(path, params=params)
                    if r.status_code == 404:
                        return None
                    if r.status_code == 429:
                        await asyncio.sleep(2 * (attempt + 1))
                        continue
                    r.raise_for_status()
                    return r.json()
                except (httpx.HTTPError, ValueError):
                    if attempt == 2:
                        return None
                    await asyncio.sleep(1 + attempt)
        return None

    # ---- parsing ---------------------------------------------------------
    @staticmethod
    def _parse(w: dict) -> Paper:
        pid = short_id(w.get("id")) or ""
        authors = [
            a.get("author", {}).get("display_name")
            for a in w.get("authorships", [])
            if a.get("author")
        ]
        venue = None
        loc = w.get("primary_location") or {}
        src = loc.get("source") or {}
        if src:
            venue = src.get("display_name")
        doi = w.get("doi")
        source_ids = {"openalex": pid}
        arxiv_url = None
        # arXiv id: from DOI (10.48550/arXiv.<id>) or from any arxiv.org location URL
        aid = arxiv_id_from_doi(doi) or _arxiv_from_locations(w)
        if aid:
            source_ids["arxiv"] = aid
            arxiv_url = f"https://arxiv.org/abs/{aid}"
        pdf_url = (loc.get("pdf_url") or (f"https://arxiv.org/pdf/{aid}" if aid else None))
        return Paper(
            id=pid,
            title=w.get("display_name") or "(untitled)",
            doi=doi,
            abstract=reconstruct_abstract(w.get("abstract_inverted_index")),
            year=w.get("publication_year"),
            authors=[a for a in authors if a],
            venue=venue,
            citation_count=w.get("cited_by_count") or 0,
            referenced_works=[short_id(x) for x in w.get("referenced_works", []) if x],
            url=w.get("id"),
            arxiv_url=arxiv_url,
            pdf_url=pdf_url,
            source_ids=source_ids,
        )

    # ---- id normalization ------------------------------------------------
    @staticmethod
    def _work_path(raw: str) -> str:
        r = raw.strip()
        if re.fullmatch(r"[Ww]\d+", r):
            return f"/works/{r.upper()}"
        if "openalex.org/" in r:
            return f"/works/{short_id(r)}"
        low = r.lower()
        if "arxiv" in low:
            m = re.search(r"(\d{4}\.\d{4,5})", r)
            if m:
                return f"/works/https://doi.org/10.48550/arxiv.{m.group(1)}"
        if low.startswith("doi:"):
            return f"/works/https://doi.org/{r[4:]}"
        if "doi.org/" in low:
            return f"/works/{r if r.startswith('http') else 'https://' + r}"
        if r.startswith("10."):
            return f"/works/https://doi.org/{r}"
        return f"/works/{r}"

    # ---- DataSource API --------------------------------------------------
    async def search(self, query: str, limit: int = 10) -> list[Paper]:
        ck = f"oa2:search:{query}:{limit}"
        if self.cache and (c := self.cache.get(ck)) is not None:
            return [Paper(**p) for p in c]
        data = await self._get(
            "/works", {"search": query, "per-page": limit, "select": _SELECT}
        )
        papers = [self._parse(w) for w in (data or {}).get("results", [])]
        if self.cache:
            self.cache.set(ck, [p.model_dump() for p in papers])
        return papers

    async def search_recent(self, query: str, limit: int = 15, recent_years: int = 3) -> list[Paper]:
        """Newest papers matching a topic, sorted by publication date (not relevance/
        citations). Surfaces brand-new follow-ups that have ~0 citations and whose citation
        edges aren't indexed yet — the frontier that `search` (relevance) and citation
        expansion miss.

        Robust to query phrasing: unions a precise title.search (best for a tight topic
        phrase) with a lenient full-text search (tolerant of longer queries); both are
        date-filtered and date-sorted."""
        import datetime

        from_year = datetime.datetime.now().year - recent_years
        ck = f"oa2:recent:{query}:{limit}:{from_year}"
        if self.cache and (c := self.cache.get(ck)) is not None:
            return [Paper(**p) for p in c]
        date_filter = f"from_publication_date:{from_year}-01-01"
        title_q = {
            "filter": f"title.search:{query},{date_filter}",
            "sort": "publication_date:desc", "per-page": limit, "select": _SELECT,
        }
        lenient_q = {
            "search": query, "filter": date_filter,
            "sort": "publication_date:desc", "per-page": limit, "select": _SELECT,
        }
        merged: dict[str, Paper] = {}
        for params in (title_q, lenient_q):
            data = await self._get("/works", params)
            for w in (data or {}).get("results", []):
                p = self._parse(w)
                if p.id:
                    merged.setdefault(p.id, p)
        papers = sorted(merged.values(), key=lambda p: p.year or 0, reverse=True)[: limit * 2]
        if self.cache:
            self.cache.set(ck, [p.model_dump() for p in papers])
        return papers

    async def get_paper(self, paper_id: str) -> Paper | None:
        ck = f"oa2:work:{paper_id}"
        if self.cache and (c := self.cache.get(ck)) is not None:
            return Paper(**c)
        data = await self._get(self._work_path(paper_id), {"select": _SELECT})
        if not data:
            return None
        paper = self._parse(data)
        if self.cache:
            self.cache.set(ck, paper.model_dump())
        return paper

    async def get_many(self, ids: list[str]) -> list[Paper]:
        ids = [short_id(i) for i in ids if i]
        out: list[Paper] = []
        missing: list[str] = []
        if self.cache:
            for i in ids:
                c = self.cache.get(f"oa2:work:{i}")
                if c is not None:
                    out.append(Paper(**c))
                else:
                    missing.append(i)
        else:
            missing = list(ids)

        # batch the misses, 50 ids per request
        for k in range(0, len(missing), 50):
            chunk = missing[k : k + 50]
            data = await self._get(
                "/works",
                {
                    "filter": "ids.openalex:" + "|".join(chunk),
                    "per-page": len(chunk),
                    "select": _SELECT,
                },
            )
            for w in (data or {}).get("results", []):
                p = self._parse(w)
                out.append(p)
                if self.cache:
                    self.cache.set(f"oa2:work:{p.id}", p.model_dump())
        return out

    async def get_citing(
        self, paper_id: str, limit: int = 25, sort: str = "citations", recent_years: int = 4
    ) -> list[Paper]:
        """Papers citing `paper_id`.

        sort:
          'citations'     - most-cited all-time (age-biased toward old work)
          'recent'        - newest by date (surfaces frontier, but noisy/niche)
          'recent_cited'  - among papers from the last `recent_years`, the most cited
                            (best for the *important* frontier, e.g. Mamba-tier work)
        """
        import datetime

        pid = short_id(paper_id)
        filt = f"cites:{pid}"
        if sort == "recent":
            order = "publication_date:desc"
        elif sort == "recent_cited":
            from_year = datetime.datetime.now().year - recent_years
            filt = f"cites:{pid},from_publication_date:{from_year}-01-01"
            order = "cited_by_count:desc"
        else:
            sort = "citations"
            order = "cited_by_count:desc"

        ck = f"oa2:citing:{pid}:{limit}:{sort}"
        if self.cache and (c := self.cache.get(ck)) is not None:
            return [Paper(**p) for p in c]
        data = await self._get(
            "/works",
            {"filter": filt, "sort": order, "per-page": limit, "select": _SELECT},
        )
        papers = [self._parse(w) for w in (data or {}).get("results", [])]
        if self.cache:
            self.cache.set(ck, [p.model_dump() for p in papers])
        return papers

    async def search_surveys(
        self, query: str, limit: int = 3, recent_years: int = 6
    ) -> list[Paper]:
        """Find recent survey/review papers for a field — their reference lists are an
        expert-curated reading set (a high-precision map of the field, incl. frontier)."""
        import datetime

        from_year = datetime.datetime.now().year - recent_years
        ck = f"oa2:surveys:{query}:{limit}:{from_year}"
        if self.cache and (c := self.cache.get(ck)) is not None:
            return [Paper(**p) for p in c]
        data = await self._get(
            "/works",
            {
                "search": f"{query} survey review",
                "filter": f"from_publication_date:{from_year}-01-01",
                "sort": "cited_by_count:desc",
                "per-page": limit,
                "select": _SELECT,
            },
        )
        papers = [self._parse(w) for w in (data or {}).get("results", [])]
        if self.cache:
            self.cache.set(ck, [p.model_dump() for p in papers])
        return papers

    async def aclose(self) -> None:
        await self._client.aclose()
