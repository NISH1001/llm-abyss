import httpx
import pytest

pytest.importorskip("mcp")

from abyss import Chunk, Search, Take  # noqa: E402
from abyss.mcp import MCP, RATE_LIMITED, build, render_chunks, render_papers  # noqa: E402
from abyss.settings import Settings  # noqa: E402


class FakeSearch(Search):
    async def search(self, query):
        return [Chunk(url=f"https://{i}.com", text=f"{query} {i}", title="t") for i in range(5)]


def test_render_is_url_and_text_only():
    out = render_chunks([Chunk(url="https://a.com", text="hello", title="ignored", meta={"x": 1})])
    assert out == "https://a.com\nhello"
    assert render_chunks([]) == "No results."


async def test_step_becomes_tool_with_query_only_schema_and_text_output():
    mcp = MCP("web").add(FakeSearch() >> Take(2), name="search", description="Search the web.")
    [tool] = await mcp.server.list_tools()
    assert tool.name == "search" and tool.description == "Search the web."
    assert tool.input_schema["required"] == ["query"] and list(tool.input_schema["properties"]) == ["query"]
    assert tool.output_schema is None  # no structured duplicate of the text

    result = await mcp.server.call_tool("search", {"query": "zram"})
    assert not result.is_error and result.structured_content is None
    assert result.content[0].text == "https://0.com\nzram 0\n\nhttps://1.com\nzram 1"


def test_settings_defaults_dotenv_and_env_precedence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for k in ("SEARXNG_URL", "SEARCH_TOP_K", "SEARCH_TIMEOUT"):
        monkeypatch.delenv(k, raising=False)
    assert Settings().search_top_k == 5

    (tmp_path / ".env").write_text(
        "SEARCH_TOP_K=3   # inline comment\nSEARXNG_URL=http://x:1\nLLM_PORT=4242\n"
    )
    s = Settings()
    assert s.search_top_k == 3 and s.searxng_url == "http://x:1"  # .env read, unknown LLM_PORT ignored

    monkeypatch.setenv("SEARCH_TOP_K", "7")
    assert Settings().search_top_k == 7  # env var wins over .env


def test_settings_reject_bad_values(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SEARCH_TOP_K", "lots")
    with pytest.raises(ValueError):
        Settings()


async def test_build_uses_settings():
    mcp = build("web", Settings(search_top_k=2, searxng_url="http://x:1", _env_file=None))
    [tool] = await mcp.server.list_tools()
    assert tool.name == "search"


def test_kb_settings_have_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = Settings()
    assert (s.kb_min_words, s.kb_window_words, s.chunk_top_k) == (7, 64, 3)


class FailingSearch(Search):
    def __init__(self, status):
        self.status = status

    async def search(self, query):
        request = httpx.Request("GET", "https://api.example/search")
        response = httpx.Response(self.status, request=request)
        raise httpx.HTTPStatusError("boom", request=request, response=response)


async def test_rate_limit_becomes_a_message_other_errors_stay_errors():
    mcp = MCP("t").add(FailingSearch(429), name="limited", description="d")
    mcp.add(FailingSearch(500), name="broken", description="d")
    limited = await mcp.server.call_tool("limited", {"query": "q"})
    assert not limited.is_error and limited.content[0].text == RATE_LIMITED
    with pytest.raises(Exception) as raised:  # not a 429: still an error, as before
        await mcp.server.call_tool("broken", {"query": "q"})
    assert isinstance(raised.value.__cause__, httpx.HTTPStatusError)


def test_render_papers_prefers_tldr_and_skips_missing_info():
    full = Chunk(
        url="https://s2/p1",
        text="long abstract",
        title="Paper",
        meta={"year": 2021, "citations": 42, "tldr": "Short."},
    )
    bare = Chunk(url="https://s2/p2", text="only abstract", title="Bare", meta={})
    assert (
        render_papers([full, bare])
        == "Paper (2021, 42 citations)\nhttps://s2/p1\nShort.\n\nBare\nhttps://s2/p2\nonly abstract"
    )
    one = Chunk(url="u", text="t", title="One", meta={"citations": 1})
    assert render_papers([one]).startswith("One (1 citation)\n")
    assert render_papers([]) == "No results."


def test_env_local_wins_over_env_and_key_is_secret(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    (tmp_path / ".env").write_text("SEMANTIC_SCHOLAR_API_KEY=from-env\n")
    (tmp_path / ".env.local").write_text("SEMANTIC_SCHOLAR_API_KEY=from-local\n")
    key = Settings().semantic_scholar_api_key
    assert key.get_secret_value() == "from-local" and "from-local" not in repr(Settings())


async def test_build_papers_passes_the_key_from_settings():
    cfg = Settings(semantic_scholar_api_key="k", search_top_k=4, _env_file=None)
    [tool] = await build("papers", cfg).server.list_tools()
    assert tool.name == "search" and "papers" in tool.description
