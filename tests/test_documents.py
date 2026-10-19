from pathlib import Path

from abyss import Chunk, DocumentSearcher, MinWords, Take, Window
from abyss.search.documents import title_of
from abyss.utils import find_hits, query_terms, window_around


def make(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


def test_query_terms_drop_short_and_stopwords_and_dedupe():
    assert query_terms("How did I set up ZRAM and zram swap?") == ["set", "zram", "swap"]


def test_hits_match_word_starts_only():
    assert [t for _, t in find_hits("helm overwhelm swapfile", ["helm", "swap"])] == ["helm", "swap"]
    assert find_hits("any text", []) == []


def test_title_decodes_logseq_names():
    assert title_of(Path("pages/Article___life lessons%3A 2022.md")) == "Article/life lessons: 2022"


def test_window_counts_words_and_centres_on_densest_cluster():
    text = "zram " + "filler " * 200 + "here zram and swap together " + "filler " * 200
    out = window_around(text, find_hits(text, ["zram", "swap"]), 10)
    assert "zram and swap" in out and out.startswith("… ") and out.endswith(" …")
    assert len(out.removeprefix("… ").removesuffix(" …").split()) == 10


def test_window_without_hits_takes_the_start_and_short_text_passes():
    assert window_around("one two three four", [], 2) == "one two …"
    assert window_around("just  a\nfew words", [], 64) == "just a few words"


async def test_ranks_by_distinct_terms_then_hits_with_title_bonus(tmp_path):
    root = make(tmp_path, {
        "pages/Zram.md": "zram is compressed swap in ram, used as swap",
        "pages/misc.md": "swap swap swap swap swap",
        "pages/other.md": "nothing relevant here at all",
        "journals/2026_10_01.md": "set up zram today",
    })  # fmt: skip
    chunks = await DocumentSearcher(root).run("zram swap")
    assert [c.url for c in chunks] == ["pages/Zram.md", "pages/misc.md", "journals/2026_10_01.md"]
    assert chunks[0].title == "Zram" and chunks[0].meta["terms"] == ["swap", "zram"]
    assert chunks[0].text == "zram is compressed swap in ram, used as swap"  # whole file; Window cuts it
    assert all(c.meta["query"] == "zram swap" for c in chunks)


async def test_include_title_false_searches_body_only(tmp_path):
    root = make(tmp_path, {"Zram.md": "nothing about it", "b.md": "zram in the body"})
    assert {c.url for c in await DocumentSearcher(root).run("zram")} == {"Zram.md", "b.md"}
    assert [c.url for c in await DocumentSearcher(root, include_title=False).run("zram")] == ["b.md"]


async def test_full_chain_globs_minwords_take_window(tmp_path):
    long_page = "intro " * 100 + "zram makes compressed swap in memory " + "outro " * 100
    root = make(tmp_path, {
        "pages/Zram.md": "- ",
        "pages/zram notes.md": long_page,
        "logseq/bak/zram.md": "zram backup copy that should never be searched at all",
    })  # fmt: skip
    kb = DocumentSearcher(root, globs=("pages/**/*.md",)) >> MinWords(7) >> Take(5) >> Window(8)
    [chunk] = await kb.run("zram swap")
    assert chunk.url == "pages/zram notes.md"
    assert "zram makes compressed swap" in chunk.text and len(chunk.text.split()) <= 10


async def test_window_works_on_any_chunk_stream():
    c = Chunk(url="u", text="a b c zram d e f g h i j", meta={"query": "zram"})
    out = (await (Window(3)).run(c))[0]
    assert out.text == "… c zram d …" and c.text.startswith("a b")  # original chunk untouched


async def test_no_terms_or_no_matches_give_nothing(tmp_path):
    root = make(tmp_path, {"a.md": "some text"})
    assert await DocumentSearcher(root).run("a an the") == []
    assert await DocumentSearcher(root).run("missing") == []


async def test_window_falls_back_to_title_words_when_nothing_else_matches():
    c = Chunk(
        url="Zram.md",
        text="filler " * 50 + "zram setup notes " + "filler " * 50,
        title="Zram",
        meta={"query": "zram"},
    )
    [out] = await Window(6).run(c)
    assert "zram setup notes" in out.text


async def test_window_skips_query_words_already_in_the_title():
    text = "intro - setup steps for the swapfile\n" + "filler " * 80 + "zram zram zram zram"
    c = Chunk(url="Zram.md", text=text, title="Zram", meta={"query": "zram setup"})
    [out] = await Window(8).run(c)
    assert "setup steps" in out.text  # "zram" is in the title, so the window goes to "setup"
