import pytest

pytest.importorskip("mcp")

from abyss import Chunk, Searcher, Take  # noqa: E402
from abyss.mcp import MCP, render_chunks  # noqa: E402


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
