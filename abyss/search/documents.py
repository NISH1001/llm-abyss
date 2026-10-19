"""Grep-style search over a folder of text files. No index: every query scans the files.

- **Match**: a lowercase substring check skips files without any query word (fast, in C); the rest get one
  case-insensitive regex anchored at word starts. With `include_title`, the file name is searched too.
- **Order**: simple, like grep with a tally. More distinct query words first, then more hits (capped), with a
  bonus for words in the file name. Proper ranking belongs in a separate step, e.g. a BM25 ranker.
- **Output**: one chunk per matching file with the whole file as its text. Cut it down with `Window`.
"""

import asyncio
import time
from pathlib import Path
from urllib.parse import unquote

from loguru import logger

from abyss.search._base import Searcher
from abyss.types import Chunk
from abyss.utils import find_hits, query_terms, terms_pattern


class DocumentSearcher(Searcher):
    """Grep-style search: query -> files under `root` containing the query words, best first.

    `globs` are relative to `root` (`**` allowed). `include_title` searches the file name with the body and
    boosts files whose name matches. `debug=True` logs scan stats through loguru.

        DocumentSearcher("~/notes") >> MinWords(7) >> Take(5) >> Window(64)
    """

    def __init__(
        self,
        root: str | Path,
        *,
        globs: tuple[str, ...] = ("**/*.md",),
        include_title: bool = True,
        debug: bool = False,
    ) -> None:
        self.root = Path(root).expanduser()
        self.globs = tuple(globs)
        self.include_title = include_title
        self.debug = debug

    async def search(self, query: str) -> list[Chunk]:
        return await asyncio.to_thread(self._search, query)

    def _search(self, query: str) -> list[Chunk]:
        terms = query_terms(query)
        if not terms:
            return []
        t0 = time.perf_counter()
        pattern = terms_pattern(terms)
        n_files = 0
        chunks: list[Chunk] = []
        for path in self._files():
            try:
                body = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            n_files += 1
            title = title_of(path)
            text = f"{title}\n{body}" if self.include_title else body
            low = text.lower()
            if not any(t in low for t in terms):  # cheap substring prefilter; the regex runs on few files
                continue
            hits = find_hits(text, terms, pattern)
            if not hits:
                continue
            found = {t for _, t in hits}
            in_title = {t for pos, t in hits if pos < len(title)} if self.include_title else set()
            score = 10.0 * len(found) + 5.0 * len(in_title) + 0.5 * min(len(hits), 20)
            meta = {"path": str(path), "hits": len(hits), "terms": sorted(found)}
            chunks.append(
                Chunk(url=str(path.relative_to(self.root)), text=body, title=title, score=score, meta=meta)
            )
        chunks.sort(key=lambda c: c.score, reverse=True)
        if self.debug:
            logger.debug(
                f"{self!r}: {query!r} -> terms={terms} scanned={n_files} matched={len(chunks)} "
                f"in {time.perf_counter() - t0:.2f}s"
            )
        return chunks

    def _files(self) -> list[Path]:
        """Files matching any glob under root, each once, in a stable order."""
        found: dict[Path, None] = {}
        for g in self.globs:
            for path in sorted(self.root.glob(g)):
                found.setdefault(path, None)  # a directory matching a glob fails to read and is skipped
        return list(found)

    def __repr__(self) -> str:
        return f"DocumentSearcher({str(self.root)!r}, globs={self.globs})"


def title_of(path: Path) -> str:
    """File name as a page title. Logseq encodes '/' in names as '___' and other characters as %XX."""
    return unquote(path.stem).replace("___", "/")
