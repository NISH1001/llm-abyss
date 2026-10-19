import json
import subprocess
import sys

import httpx
import pytest

from abyss import Chunk, Config, NotBlocked, Searcher, SearxngSearcher, Take
from abyss.search import is_blocked


class FakeSearcher(Searcher):
    def __init__(self, urls):
        self.urls = urls

    async def search(self, query):
        return [Chunk(url=u, text=f"{query} snippet {i}") for i, u in enumerate(self.urls)]


async def test_searcher_chains_and_tags_query():
    s = FakeSearcher(["https://a.com", "https://youtube.com/x", "https://b.com", "https://c.com"])
    chunks = await (s >> NotBlocked() >> Take(2)).run("zram")
    assert [c.url for c in chunks] == ["https://a.com", "https://b.com"]
    assert all(c.meta["query"] == "zram" for c in chunks)


def test_is_blocked_matches_subdomains_and_www():
    assert is_blocked("https://m.youtube.com/watch")
    assert is_blocked("https://www.reddit.com/r/linux")
    assert not is_blocked("https://notyoutube.com/")
    assert not is_blocked("https://wiki.archlinux.org/title/Swap")


def _searxng(payload, seen):
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_searxng_parses_dedups_truncates_and_drops_empty():
    payload = {
        "results": [
            {"url": "https://a.com", "title": " A ", "content": "x" * 500, "engine": "brave"},
            {"url": "https://a.com", "title": "dup", "content": "dup", "engine": "bing"},
            {"url": "https://b.com", "title": "B", "content": "", "engine": "bing"},
            {
                "url": "https://c.com",
                "title": "C",
                "content": "line\n  two",
                "publishedDate": "2026-01-02T00:00",
            },
        ]
    }
    seen = []
    s = SearxngSearcher("http://searx:8080/", snippet_chars=300, client=_searxng(payload, seen))
    chunks = await s.search("zram")

    assert [c.url for c in chunks] == ["https://a.com", "https://c.com"]
    assert chunks[0].title == "A" and len(chunks[0].text) == 300
    assert chunks[1].text == "line two"
    assert chunks[0].meta == {"engine": "brave", "rank": 0}
    assert chunks[1].meta["rank"] == 1 and chunks[1].meta["date"] == "2026-01-02"
    url = seen[0].url
    assert url.path == "/search" and url.params["format"] == "json" and url.params["categories"] == "general"


async def test_searxng_http_error_raises():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(httpx.HTTPStatusError):
        await SearxngSearcher(client=client).search("q")


def test_config_defaults_and_env_overrides():
    assert Config().search_top_k == 5 and Config().snippet_chars == 300
    cfg = Config.from_env({"SEARCH_TOP_K": "3", "SEARXNG_URL": "http://x:1", "SEARCH_TIMEOUT": "2.5"})
    assert cfg.search_top_k == 3 and cfg.searxng_url == "http://x:1" and cfg.search_timeout == 2.5


def test_import_abyss_does_not_load_httpx():
    code = (
        "import sys, abyss; assert 'httpx' not in sys.modules, 'httpx loaded eagerly'; print(json.dumps(1))"
    )
    out = subprocess.run([sys.executable, "-c", "import json;" + code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == 1
