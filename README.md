# llm-abyss

Opinionated tooling around the abyss of LLMs: composable, async-first retrieval steps, servable as MCP tools.

The repo has two parts:

1. **`abyss`, the library.** Small components (searchers, filters, and soon crawlers, chunkers and rankers)
   that snap together into streaming pipelines with `>>`. The core depends only on `httpx`.
2. **Local serving.** SearXNG in Docker plus a llama.cpp server whose web UI can call abyss pipelines as
   tools. See [docs/DEPLOY.md](docs/DEPLOY.md).

## Install

```bash
uv add "llm-abyss @ git+https://github.com/NISH1001/llm-abyss"         # core
uv add "llm-abyss[mcp] @ git+https://github.com/NISH1001/llm-abyss"    # + MCP serving and Settings
```

The distribution is `llm-abyss`; the import is `abyss`. Try it without installing anything, against any
SearXNG instance with the JSON format enabled:

```bash
uv run --with "llm-abyss @ git+https://github.com/NISH1001/llm-abyss" python -c '
import asyncio
from abyss import SearxngSearcher, NotBlocked, Take

search = SearxngSearcher("http://127.0.0.1:4243") >> NotBlocked() >> Take(3)
for c in asyncio.run(search.run("what is zram")):
    print(c.url, "|", c.text)'
```

## How it composes

Everything is a **Step**: something that turns an async stream of items into another async stream. `>>`
chains steps into a new step, and building a chain runs nothing.

```python
search = SearxngSearcher(url) >> NotBlocked() >> Take(5)

chunks = await search.run("zram vs zswap")         # list of everything
async for chunk in search.stream("zram vs zswap"):  # items as they arrive
    ...
```

- **Items stream.** A step passes each result on the moment it is ready, so item 1 can be three steps
  downstream while item 5 is still in the first.
- **`Take(n)` stops early.** Once it has n items it closes the stream and cancels the work still running
  upstream.
- **Concurrency lives in the step.** Async per-item steps run their items concurrently, with an optional
  `concurrency=` cap.
- **Plain functions chain too.** A function becomes a `Map`, so `search >> (lambda c: c.url)` works.

### Data: one `Chunk` type

Every stage passes the same small record:

```python
@dataclass
class Chunk:
    url: str
    text: str           # snippet after search; page or window text after later stages
    title: str = ""
    score: float = 0.0
    meta: dict = field(default_factory=dict)  # query, engine, rank, date, ...
```

Searchers tag each chunk with `meta["query"]`, so later steps (a ranker) can read the query from the
stream instead of needing it passed in.

### Building blocks

| Step | Shape | Notes |
|---|---|---|
| `Map(fn, concurrency=None)` | 1 → 1 | returning `None` drops the item; sync keeps order |
| `FlatMap(fn, concurrency=None)` | 1 → N | `fn` returns an async iterable |
| `Filter(pred)` | 1 → 0..1 | `Predicate` combines with `&`, `\|`, `~` |
| `Take(n)` | N → n | cancels upstream once full |
| `once(x)`, `collect(stream)` | | source and sink, used by `run`/`stream` |

### Components

| Component | Shape | Status |
|---|---|---|
| `Searcher` | query → N chunks | base class: implement `search(query)` |
| `SearxngSearcher(base_url, categories="general", timeout=8.0)` | query → N chunks | `categories="science"` for papers |
| `DocumentSearcher(root, globs=("**/*.md",), include_title=True)` | query → N chunks | grep-style scan of local files, no index; whole file as text |
| `NotBlocked(domains=BLOCKED_DOMAINS)` | filter | drops social and video sites |
| `MinWords(n=7)` | filter | drops stub pages and empty snippets |
| `Window(words=64)` | 1 → 1 | cuts text to the words around the best match for `meta["query"]` |
| Crawler, Chunker, Ranker | chunk → chunk(s) | planned |

### Example: searching a folder of notes

`DocumentSearcher` is grep-style: every query scans the files, so there is no index to build or keep fresh.
On its own it returns every matching file, best first, each with the whole file as its text:

```python
from abyss import DocumentSearcher, MinWords, Take, Window

searcher = DocumentSearcher("~/notes", globs=("pages/**/*.md", "journals/**/*.md"))
chunks = await searcher.run("zram swap")   # every matching file, whole pages
for c in chunks[:3]:
    print(c.score, c.url, c.meta["terms"])
```

Chain steps onto it to shape what comes out. Each `>>` returns a new `Chain`; the searcher itself is
unchanged, and nothing runs until `.run()` or `.stream()`:

```python
kb = searcher >> MinWords(7) >> Take(3) >> Window(64)

chunks = await kb.run("zram swap")           # 3 chunks of about 64 words
async for chunk in kb.stream("zram swap"):   # or one at a time, as they arrive
    print(chunk.url, chunk.text)

print(kb)  # DocumentSearcher('~/notes', ...) >> MinWords(7) >> Take(3) >> Window(64)
```

| Step | What it does here |
|---|---|
| `searcher` | finds the files that contain the query words, best first |
| `MinWords(7)` | drops stub pages that are only a title or a tag |
| `Take(3)` | keeps the first three, then stops the stream |
| `Window(64)` | cuts each page to the 64 words around its best match for the query |

Order matters. `MinWords` before `Take` judges whole pages and lets `Take` fill up from the next results.
`Window` after `Take` cuts only the pages that are kept.

A chain is a plain value: build it once and run it on any query, or branch one searcher into several chains:

```python
whole_pages = searcher >> MinWords(7) >> Take(5)
excerpts = searcher >> MinWords(7) >> Take(3) >> Window(64)   # what kb_search serves
```

How matching and ordering work:

- **Matching** is case-insensitive at word starts, so "swap" finds "swapfile" and "helm" skips "overwhelm".
  With `include_title=True` (the default) the file name is searched along with the body.
- **Order** is a simple tally: more distinct query words first, then more hits, plus a bonus for words in
  the file name. Very long pages that mention everything can rank high; a ranking step that accounts for
  page length (BM25) is planned to sit between the searcher and `Take`.
- **`Window`** skips query words already in the page's title when it picks the excerpt. On a page named
  "Zram", the query "zram setup" shows the part about setup rather than the parts that just repeat "zram".

## Write your own component

Subclass the role and implement one method. Chaining, streaming and concurrency come from the base class.

```python
from abyss import Chunk, Searcher, Take

class NotesSearcher(Searcher):
    async def search(self, query: str) -> list[Chunk]:
        return [Chunk(url="file:///notes.md", text=f"my notes about {query}")]

notes = NotesSearcher() >> Take(5)   # chains like any other step
```

For a step that is not a searcher, subclass `Map`, `FlatMap` or `Filter`, or subclass `Step` and implement
`__call__(items) -> AsyncIterator`.

## Serve steps as MCP tools

Needs the `[mcp]` extra. Any step or chain becomes a tool that takes one `query: str` and returns plain
text, one result per block as URL plus text. Input and output stay minimal so the model's context stays
small.

```python
# my_server.py
from abyss import NotBlocked, SearxngSearcher, Settings, Take
from abyss.mcp import MCP

s = Settings()  # .env and env vars
web = SearxngSearcher(s.searxng_url) >> NotBlocked() >> Take(s.search_top_k)
papers = SearxngSearcher(s.searxng_url, categories="science") >> Take(3)

mcp = MCP("abyss")
mcp.add(web, name="web_search", description="Search the web. Returns URL and snippet per result.")
mcp.add(papers, name="paper_search", description="Search academic papers. Returns URL and snippet per result.")

if __name__ == "__main__":
    mcp.run()  # stdio
```

Point any MCP client at `python my_server.py`. Pass `render=` to `add` to control the output text.

The package also ships a stock server, `abyss-mcp <group>`, built from `Settings`: `abyss-mcp web` serves web
search over SearXNG, and `abyss-mcp kb` serves grep-style search over a Logseq graph (`LOGSEQ_KB`).

## Settings

`abyss.settings.Settings` (pydantic-settings, in the `[mcp]` extra) holds project-level defaults. It reads
`.env` from the working directory; environment variables win; unknown keys are ignored. Components never
read it: they take constructor arguments, and whatever assembles them reads `Settings` and passes values in.

| Setting | Default | Used by |
|---|---|---|
| `searxng_url` | `http://127.0.0.1:4243` | search |
| `search_categories` | `general` | search |
| `search_timeout` | `8.0` | search |
| `search_top_k` | `5` | search |
| `logseq_kb` | unset | path of a Logseq graph; enables the `kb_search` tool |
| `kb_min_words`, `kb_window_words` | `7`, `64` | `kb_search`: stub cutoff and excerpt length |
| `debug` | `false` | log per-call details to stderr |
| `crawl_concurrency`, `crawl_timeout`, `crawl_max_bytes` | `3`, `6.0`, `1500000` | crawler (planned) |
| `chunk_top_k` | `3` | `kb_search` results; later the ranker |
| `chunk_size`, `chunk_overlap` | `512`, `64` | chunker (planned) |

## Local serving

SearXNG runs in Docker, llama-server runs on the host in tmux, and llama-server spawns `abyss-mcp` itself
over stdio, so there is no MCP port.

```bash
cp .env.example .env          # set SEARXNG_SECRET
uv sync --extra mcp
docker compose up -d          # SearXNG
deploy/llm.sh start           # llama-server with the web_search tool
```

Everything else, including settings, remote access over Tailscale and troubleshooting, is in
[docs/DEPLOY.md](docs/DEPLOY.md).

## Development

```bash
uv sync --extra mcp
uv run pytest          # parallel via xdist; -n 0 for a quick serial run
uv run ruff check abyss tests && uv run ruff format abyss tests
```

## License

MIT
