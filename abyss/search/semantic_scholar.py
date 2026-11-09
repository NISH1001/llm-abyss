import asyncio
import time

import httpx
from loguru import logger

from abyss.search._base import Search
from abyss.types import Chunk


class SemanticScholarSearch(Search):
    """Paper search over the Semantic Scholar Graph API, in its relevance order. Text is the abstract, or the
    TLDR when there is no abstract; papers with neither are dropped. Year, authors, citations, venue, TLDR and
    DOI/arXiv/PDF links go in `meta` when present.

    `api_key` is optional: without one, requests share a public pool that often answers 429. A key allows 1
    request per second, so queries run one at a time and requests start at least `min_interval` seconds apart.
    A 429 is still retried `retries` times after `backoff * 2**attempt` seconds."""

    URL = "https://api.semanticscholar.org/graph/v1/paper/search"
    FIELDS = "title,url,abstract,tldr,year,venue,citationCount,authors,externalIds,openAccessPdf"
    concurrency = 1

    def __init__(
        self,
        api_key: str | None = None,
        *,
        limit: int = 10,
        timeout: float = 10.0,
        min_interval: float = 1.0,
        retries: int = 3,
        backoff: float = 1.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.limit = limit
        self.timeout = timeout
        self.min_interval = min_interval
        self.retries = retries
        self.backoff = backoff
        self.client = client
        self._lock = asyncio.Lock()  # one request at a time, spaced by min_interval
        self._last = float("-inf")  # monotonic start time of the last request

    async def search(self, query: str) -> list[Chunk]:
        if self.client is not None:
            response = await self._get(self.client, query)
        else:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await self._get(client, query)
        response.raise_for_status()

        chunks: list[Chunk] = []
        for paper in response.json().get("data") or []:
            tldr = " ".join(((paper.get("tldr") or {}).get("text") or "").split())
            text = " ".join((paper.get("abstract") or "").split()) or tldr
            if not paper.get("url") or not text:
                continue
            ids = paper.get("externalIds") or {}
            optional = {
                "year": paper.get("year"),
                "venue": paper.get("venue"),
                "citations": paper.get("citationCount"),
                "tldr": tldr,
                "doi": ids.get("DOI"),
                "arxiv": ids.get("ArXiv"),
                "pdf": (paper.get("openAccessPdf") or {}).get("url"),  # "" when there is no PDF
            }
            meta = {
                "engine": "semanticscholar",
                "rank": len(chunks),
                "paper_id": paper.get("paperId", ""),
                "authors": [a["name"] for a in paper.get("authors") or [] if a.get("name")],
            } | {k: v for k, v in optional.items() if v not in (None, "")}
            title = " ".join((paper.get("title") or "").split())
            chunks.append(Chunk(url=paper["url"], text=text, title=title, meta=meta))
        return chunks

    async def _get(self, client: httpx.AsyncClient, query: str) -> httpx.Response:
        params = {"query": query, "limit": self.limit, "fields": self.FIELDS}
        headers = {"x-api-key": self.api_key} if self.api_key else {}
        attempt = 0
        async with self._lock:
            while True:
                if (gap := self._last + self.min_interval - time.monotonic()) > 0:
                    await asyncio.sleep(gap)
                self._last = time.monotonic()
                response = await client.get(self.URL, params=params, headers=headers)
                if response.status_code != 429 or attempt >= self.retries:
                    return response
                wait = self.backoff * 2**attempt
                attempt += 1
                logger.debug(f"semantic scholar: 429, retry {attempt}/{self.retries} in {wait:.1f}s")
                await asyncio.sleep(wait)

    def __repr__(self) -> str:
        key = ", api_key=..." if self.api_key else ""
        return f"SemanticScholarSearch(limit={self.limit}{key})"
