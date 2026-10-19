"""Serve any Step as an MCP tool over stdio. Needs the [mcp] extra.

Every tool takes one `query: str` and returns plain text: input and output kept minimal so the model's
context stays small. llama-server spawns this process itself (see --mcp-servers-config) and exposes each
tool as `<server>_<tool>`, so server "web" + tool "search" shows up as `web_search`.
"""

from collections.abc import Callable, Sequence

from abyss.pipeline import Step, Take
from abyss.settings import Settings
from abyss.types import Chunk


def render_chunks(chunks: Sequence[Chunk]) -> str:
    """URL + text per chunk, nothing else. The URL lets the model cite or open a source."""
    if not chunks:
        return "No results."
    return "\n\n".join(f"{c.url}\n{c.text}" for c in chunks)


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
            return render(await step.run(query))

        self.server.tool(name=name, description=description, structured_output=False)(tool)
        return self

    def run(self) -> None:
        self.server.run("stdio")


def build(settings: Settings | None = None) -> MCP:
    """The stock server: one `search` tool over SearXNG, snippets only."""
    from abyss.search import NotBlocked
    from abyss.search.searxng import SearxngSearcher

    cfg = settings or Settings()
    search = (
        SearxngSearcher(cfg.searxng_url, categories=cfg.search_categories, timeout=cfg.search_timeout)
        >> NotBlocked()
        >> Take(cfg.search_top_k)
    )
    return MCP("web").add(
        search,
        name="search",
        description="Search the web for current information. Returns the top results as URL and snippet.",
    )


def main() -> None:
    build().run()
