"""Small text helpers shared by searchers and steps."""

import re
from bisect import bisect_right
from collections import Counter

_WORD = re.compile(r"\w+")
_TOKEN = re.compile(r"\S+")
STOPWORDS = frozenset(
    """the and for are but not you all any can had her was one our out has have how what when where which
    who why with this that from they will would there their about into than then them these those does did
    doing your yours mine also just like more most some such only very""".split()
)


def query_terms(query: str) -> list[str]:
    """Lowercase words of 3+ characters, stopwords dropped, order kept, each once."""
    words = (w.lower() for w in _WORD.findall(query))
    return list(dict.fromkeys(w for w in words if len(w) >= 3 and w not in STOPWORDS))


def terms_pattern(terms: list[str]) -> re.Pattern[str]:
    """Case-insensitive regex matching any term at a word start ("swap" in "swapfile", not "helm" in
    "overwhelm"). Longer terms are tried first."""
    return re.compile(r"\b(?:" + "|".join(map(re.escape, sorted(terms, key=len, reverse=True))) + ")", re.I)


def find_hits(text: str, terms: list[str], pattern: re.Pattern[str] | None = None) -> list[tuple[int, str]]:
    """(character offset, term) for every match of `terms` in `text`. No terms: no hits."""
    if not terms:
        return []
    pattern = pattern or terms_pattern(terms)
    return [(m.start(), _term_of(m.group(), terms)) for m in pattern.finditer(text)]


def _term_of(matched: str, terms: list[str]) -> str:
    low = matched.lower()
    return low if low in terms else next(t for t in terms if low.startswith(t))


def window_around(text: str, hits: list[tuple[int, str]], width: int) -> str:
    """`width` consecutive words of `text` holding the most distinct terms (ties: most hits, then earliest),
    whitespace collapsed, with ellipses where it was cut. No hits: the first `width` words."""
    spans = list(_TOKEN.finditer(text))
    if not hits:
        start, end = 0, min(width, len(spans))
    else:
        starts = [m.start() for m in spans]
        at = [max(0, bisect_right(starts, pos) - 1) for pos, _ in hits]  # word index of each hit
        best = (0, 0, 0)  # distinct, count, -index of first hit
        counts: Counter[str] = Counter()
        lo = 0
        for hi, (_, term) in enumerate(hits):  # two pointers: hits[lo..hi] all within `width` words
            counts[term] += 1
            while at[hi] - at[lo] >= width:
                counts[hits[lo][1]] -= 1
                if not counts[hits[lo][1]]:
                    del counts[hits[lo][1]]
                lo += 1
            best = max(best, (len(counts), hi - lo + 1, -lo))
        first = -best[2]
        centre = (at[first] + at[first + best[1] - 1]) // 2
        end = min(len(spans), max(0, centre - width // 2) + width)
        start = max(0, end - width)
    body = " ".join(m.group() for m in spans[start:end])
    return ("… " if start > 0 else "") + body + (" …" if end < len(spans) else "")
