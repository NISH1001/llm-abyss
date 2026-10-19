"""Opinionated tooling around the abyss of LLMs."""

from abyss.pipeline import Chain, Filter, FlatMap, Map, Predicate, Step, Take, collect, once
from abyss.search import NotBlocked, Searcher
from abyss.types import Chunk

__all__ = [
    "Chain", "Chunk", "Filter", "FlatMap", "Map", "NotBlocked", "Predicate", "Searcher",
    "SearxngSearcher", "Step", "Take", "collect", "once",
]  # fmt: skip


def __getattr__(name: str):  # lazy: heavy or optional imports load on first use
    if name == "SearxngSearcher":
        from abyss.search.searxng import SearxngSearcher

        return SearxngSearcher
    raise AttributeError(name)
