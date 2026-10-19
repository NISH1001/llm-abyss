import re

import httpx

from abyss.search._base import Searcher
from abyss.types import Chunk

_WS = re.compile(r"\s+")


class SearxngSearcher(Searcher):
    """A self-hosted SearXNG instance with the JSON format enabled. Results come back in SearXNG's rank order,
    each URL once, hits without a snippet dropped. Snippets are kept whole unless `snippet_chars` is set."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:4243",
        *,
        categories: str = "general",
        timeout: float = 8.0,
        snippet_chars: int | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.categories = categories
        self.timeout = timeout
        self.snippet_chars = snippet_chars
        self.client = client

    async def search(self, query: str) -> list[Chunk]:
        params = {"q": query, "format": "json", "categories": self.categories}
        if self.client is not None:
            response = await self.client.get(f"{self.base_url}/search", params=params)
        else:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/search", params=params)
        response.raise_for_status()

        chunks: list[Chunk] = []
        seen: set[str] = set()
        for result in response.json().get("results", []):
            url = result.get("url") or ""
            text = _WS.sub(" ", result.get("content") or "").strip()
            if self.snippet_chars:
                text = text[: self.snippet_chars]
            if not url or not text or url in seen:
                continue
            seen.add(url)
            meta = {"engine": result.get("engine", ""), "rank": len(chunks)}
            if date := result.get("publishedDate"):
                meta["date"] = str(date)[:10]
            chunks.append(Chunk(url=url, text=text, title=(result.get("title") or "").strip(), meta=meta))
        return chunks

    def __repr__(self) -> str:
        return f"SearxngSearcher({self.base_url!r}, categories={self.categories!r})"
