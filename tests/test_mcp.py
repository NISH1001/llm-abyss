import pytest

pytest.importorskip("mcp")

from abyss import Chunk, Searcher, Take  # noqa: E402
from abyss.mcp import MCP, Settings, build, render_chunks  # noqa: E402


class FakeSearcher(Searcher):
    async def search(self, query):
        return [Chunk(url=f"https://{i}.com", text=f"{query} {i}", title="t") for i in range(5)]


def test_render_is_url_and_text_only():
    out = render_chunks([Chunk(url="https://a.com", text="hello", title="ignored", meta={"x": 1})])
    assert out == "https://a.com\nhello"
    assert render_chunks([]) == "No results."


async def test_step_becomes_tool_with_query_only_schema_and_text_output():
    mcp = MCP("web").add(FakeSearcher() >> Take(2), name="search", description="Search the web.")
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
    mcp = build(Settings(search_top_k=2, searxng_url="http://x:1", _env_file=None))
    [tool] = await mcp.server.list_tools()
    assert tool.name == "search"
