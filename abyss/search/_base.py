from collections.abc import AsyncIterator
from urllib.parse import urlsplit

from abyss.pipeline import Filter, FlatMap, Step
from abyss.types import Chunk

# Social and video sites: mostly reposts and comments, or no usable text.
BLOCKED_DOMAINS = (
    "reddit.com", "youtube.com", "youtu.be", "facebook.com", "fb.com", "instagram.com", "tiktok.com",
    "twitter.com", "x.com", "threads.net", "threads.com", "linkedin.com", "pinterest.com", "quora.com",
)  # fmt: skip


class Searcher(Step):
    """query -> N chunks, text = snippet. Implement `search`; streaming and chaining come from Step.
    Every chunk gets `meta["query"]`, so later steps (a ranker) can read the query from the stream."""

    concurrency: int | None = None  # queries searched at once

    async def search(self, query: str) -> list[Chunk]:
        raise NotImplementedError(f"{type(self).__name__}.search")

    def __call__(self, queries: AsyncIterator[str]) -> AsyncIterator[Chunk]:
        async def chunks(query: str) -> AsyncIterator[Chunk]:
            for chunk in await self.search(query):
                chunk.meta.setdefault("query", query)
                yield chunk

        return FlatMap(chunks, self.concurrency)(queries)


class NotBlocked(Filter):
    """Drop chunks whose URL is on `domains` or a subdomain of one (m.youtube.com)."""

    def __init__(self, domains: tuple[str, ...] = BLOCKED_DOMAINS) -> None:
        self.domains = tuple(domains)
        super().__init__(lambda chunk: not is_blocked(chunk.url, self.domains))

    def __repr__(self) -> str:
        return f"NotBlocked({len(self.domains)} domains)"


def is_blocked(url: str, domains: tuple[str, ...] = BLOCKED_DOMAINS) -> bool:
    host = (urlsplit(url).hostname or "").removeprefix("www.")
    return any(host == d or host.endswith("." + d) for d in domains)
