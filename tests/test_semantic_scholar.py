import time

import httpx
import pytest

from abyss import SemanticScholarSearch, Take

PAPERS = {
    "total": 3,
    "offset": 0,
    "data": [
        {
            "paperId": "p1",
            "url": "https://www.semanticscholar.org/paper/p1",
            "title": " Compressed  swap ",
            "abstract": "We study\n  compressed swap.",
            "tldr": {"model": "tldr@v2.0.0", "text": "zram is fast."},
            "year": 2021,
            "venue": "OSDI",
            "citationCount": 42,
            "authors": [{"authorId": "1", "name": "Ada"}, {"authorId": "2", "name": "Linus"}],
            "externalIds": {"DOI": "10.1/x", "ArXiv": "2101.00001"},
            "openAccessPdf": {"url": "https://arxiv.org/pdf/2101.00001", "status": "GREEN"},
        },
        {
            "paperId": "p2",
            "url": "https://www.semanticscholar.org/paper/p2",
            "title": "No text",
            "abstract": None,
        },
        {
            "paperId": "p3",
            "url": "https://www.semanticscholar.org/paper/p3",
            "title": "TLDR only",
            "abstract": None,
            "tldr": {"text": "short summary"},
            "year": None,
            "authors": [],
            "externalIds": None,
            "openAccessPdf": {"url": "", "status": None},  # what the API sends when there is no PDF
        },
    ],
}


def _client(responses, seen):
    it = iter(responses)

    def handler(request):
        seen.append(request)
        return next(it)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_parses_papers_and_drops_ones_without_text():
    seen = []
    s = SemanticScholarSearch(limit=5, client=_client([httpx.Response(200, json=PAPERS)], seen))
    chunks = await s.search("zram")

    assert [c.url for c in chunks] == [
        "https://www.semanticscholar.org/paper/p1",
        "https://www.semanticscholar.org/paper/p3",
    ]
    first, second = chunks
    assert first.title == "Compressed swap" and first.text == "We study compressed swap."
    assert first.meta == {
        "engine": "semanticscholar", "rank": 0, "paper_id": "p1", "year": 2021, "venue": "OSDI",
        "citations": 42, "authors": ["Ada", "Linus"], "tldr": "zram is fast.",
        "doi": "10.1/x", "arxiv": "2101.00001", "pdf": "https://arxiv.org/pdf/2101.00001",
    }  # fmt: skip
    assert second.text == "short summary" and second.meta == {
        "engine": "semanticscholar", "rank": 1, "paper_id": "p3", "authors": [], "tldr": "short summary",
    }  # fmt: skip

    url = seen[0].url
    assert url.path == "/graph/v1/paper/search"
    assert url.params["query"] == "zram" and url.params["limit"] == "5" and "abstract" in url.params["fields"]
    assert "x-api-key" not in seen[0].headers


async def test_api_key_is_sent_as_header_and_hidden_from_repr():
    seen = []
    s = SemanticScholarSearch(
        api_key="sekret", client=_client([httpx.Response(200, json={"data": []})], seen)
    )
    assert await s.search("q") == []
    assert seen[0].headers["x-api-key"] == "sekret"
    assert "sekret" not in repr(s)


async def test_retries_429_then_succeeds():
    seen = []
    responses = [httpx.Response(429), httpx.Response(429), httpx.Response(200, json=PAPERS)]
    s = SemanticScholarSearch(retries=2, backoff=0, min_interval=0, client=_client(responses, seen))
    assert len(await s.search("zram")) == 2
    assert len(seen) == 3


async def test_gives_up_after_retries():
    seen = []
    s = SemanticScholarSearch(
        retries=1, backoff=0, min_interval=0, client=_client([httpx.Response(429)] * 2, seen)
    )
    with pytest.raises(httpx.HTTPStatusError):
        await s.search("zram")
    assert len(seen) == 2


async def test_other_errors_are_not_retried():
    seen = []
    s = SemanticScholarSearch(backoff=0, client=_client([httpx.Response(500)], seen))
    with pytest.raises(httpx.HTTPStatusError):
        await s.search("zram")
    assert len(seen) == 1


async def test_chains_and_runs_one_query_at_a_time():
    s = SemanticScholarSearch(client=_client([httpx.Response(200, json=PAPERS)], []))
    assert SemanticScholarSearch.concurrency == 1
    chunks = await (s >> Take(1)).run("zram")
    assert [c.meta["paper_id"] for c in chunks] == ["p1"] and chunks[0].meta["query"] == "zram"


async def test_requests_start_min_interval_apart():
    starts = []

    def handler(request):
        starts.append(time.monotonic())
        return httpx.Response(200, json={"data": []})

    s = SemanticScholarSearch(
        min_interval=0.2, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    await (s >> Take(10)).run("a")
    await s.search("b")
    assert len(starts) == 2 and starts[1] - starts[0] >= 0.2
