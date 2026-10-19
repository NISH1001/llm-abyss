"""Chunk steps for any chain: `searcher >> MinWords(7) >> Take(5) >> Window(64)`."""

from dataclasses import replace

from abyss.pipeline import Filter, Map
from abyss.types import Chunk
from abyss.utils import find_hits, query_terms, window_around


class MinWords(Filter):
    """Drop chunks whose text has fewer than `n` words (stub pages, empty snippets)."""

    def __init__(self, n: int = 7) -> None:
        self.n = n
        super().__init__(self._keep)

    def _keep(self, chunk: Chunk) -> bool:
        return len(chunk.text.split()) >= self.n

    def __repr__(self) -> str:
        return f"MinWords({self.n})"


class Window(Map):
    """Cut each chunk's text to `words` words around its best match for `meta["query"]` (set by every
    searcher). No query or no match: the first `words` words. Short text passes through, whitespace
    collapsed. Returns a new chunk; the input is left as is."""

    def __init__(self, words: int = 64) -> None:
        self.words = words
        super().__init__(self._cut)

    def _cut(self, chunk: Chunk) -> Chunk:
        terms = query_terms(chunk.meta.get("query", ""))
        hits = find_hits(chunk.text, terms) if terms else []
        return replace(chunk, text=window_around(chunk.text, hits, self.words))

    def __repr__(self) -> str:
        return f"Window({self.words})"
