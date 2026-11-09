"""Serve any Step as an MCP tool over stdio. Needs the [mcp] extra.

Every tool takes one `query: str` and returns plain text: input and output kept minimal so the model's
context stays small. llama-server spawns this process itself (see --mcp-servers-config) and exposes each
tool as `<server>_<tool>`, so server "web" + tool "search" shows up as `web_search`.
"""

import time
from collections.abc import Callable, Sequence

import httpx
from loguru import logger

from abyss.pipeline import Step, Take
from abyss.settings import Settings
from abyss.types import Chunk

RATE_LIMITED = "The search service is rate-limiting requests right now. Try again in a few seconds."


def render_chunks(chunks: Sequence[Chunk]) -> str:
    """URL + text per chunk, nothing else. The URL lets the model cite or open a source."""
    if not chunks:
        return "No results."
    return "\n\n".join(f"{c.url}\n{c.text}" for c in chunks)


def render_papers(chunks: Sequence[Chunk]) -> str:
    """Per paper: title with year and citations, URL, then the TLDR (or the abstract when there is none)."""
    if not chunks:
        return "No results."
    blocks: list[str] = []
    for c in chunks:
        info = [str(c.meta["year"])] if "year" in c.meta else []
        if "citations" in c.meta:
            n = c.meta["citations"]
            info.append(f"{n} citation{'' if n == 1 else 's'}")
        head = f"{c.title} ({', '.join(info)})" if info else c.title
        blocks.append(f"{head}\n{c.url}\n{c.meta.get('tldr') or c.text}")
    return "\n\n".join(blocks)


class MCP:
    def __init__(self, name: str = "abyss") -> None:
        from mcp.server.mcpserver import MCPServer  # lazy: optional extra

        self.server = MCPServer(name)

    def add(
        self,
        step: Step,
        *,
        name: str,
        description: str,
        render: Callable[[list], str] = render_chunks,
    ) -> "MCP":
        async def tool(query: str) -> str:
            t0 = time.perf_counter()
            try:
                items = await step.run(query)
            except httpx.HTTPStatusError as e:
                if e.response.status_code != 429:
                    raise
                logger.warning(f"{name}: {query!r} -> rate-limited after retries")
                return RATE_LIMITED
            logger.info(f"{name}: {query!r} -> {len(items)} results in {time.perf_counter() - t0:.2f}s")
            return render(items)

        self.server.tool(name=name, description=description, structured_output=False)(tool)
        return self

    def run(self) -> None:
        self.server.run("stdio")


def build_web(cfg: Settings) -> MCP:
    """`search` over SearXNG, snippets only."""
    from abyss.search import NotBlocked
    from abyss.search.searxng import SearxngSearch

    search = (
        SearxngSearch(cfg.searxng_url, categories=cfg.search_categories, timeout=cfg.search_timeout)
        >> NotBlocked()
        >> Take(cfg.search_top_k)
    )
    return MCP("web").add(
        search,
        name="search",
        description="Search the web for current information. Returns the top results as URL and snippet.",
    )


def build_kb(cfg: Settings) -> MCP:
    """`search` over a Logseq graph: pages and journals, stub pages dropped."""
    from abyss.search.documents import DocumentSearch
    from abyss.steps import MinWords, Window

    if cfg.logseq_kb is None:
        raise SystemExit("abyss-mcp kb: set LOGSEQ_KB to the Logseq graph folder")
    search = (
        DocumentSearch(cfg.logseq_kb, globs=("pages/**/*.md", "journals/**/*.md"), debug=cfg.debug)
        >> MinWords(cfg.kb_min_words)
        >> Take(cfg.chunk_top_k)
        >> Window(cfg.kb_window_words)
    )
    return MCP("kb").add(
        search,
        name="search",
        description=(
            "Search the user's personal notes and journals (their Logseq knowledge base). "
            "Use it whenever the user asks about their notes, what they wrote, saved or learned. "
            "Pass short keywords as the query. "
            "Returns the best-matching pages as file path and an excerpt around the match."
        ),
    )


def build_papers(cfg: Settings) -> MCP:
    """`search` over Semantic Scholar papers. SEMANTIC_SCHOLAR_API_KEY is optional; without it, requests are
    often rate-limited."""
    from abyss.search.semantic_scholar import SemanticScholarSearch

    key = cfg.semantic_scholar_api_key
    search = SemanticScholarSearch(key.get_secret_value() if key else None, limit=cfg.search_top_k)
    return MCP("papers").add(
        search,
        name="search",
        description=(
            "Search academic papers (Semantic Scholar). "
            "Use it for research questions and to find papers to cite. "
            "Returns title, year, citation count, URL and a one-sentence summary or abstract per paper."
        ),
        render=render_papers,
    )


GROUPS = {"web": build_web, "kb": build_kb, "papers": build_papers}


def build(group: str = "web", settings: Settings | None = None) -> MCP:
    """A stock server for one tool group. llama-server shows its tool as `<group>_search`."""
    if group not in GROUPS:
        raise SystemExit(f"abyss-mcp: unknown group {group!r}; choose from {', '.join(GROUPS)}")
    return GROUPS[group](settings or Settings())


def main() -> None:
    import sys

    cfg = Settings()
    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if cfg.debug else "INFO")  # stdout carries the MCP protocol
    logger.enable("abyss")
    build(sys.argv[1] if len(sys.argv) > 1 else "web", cfg).run()
