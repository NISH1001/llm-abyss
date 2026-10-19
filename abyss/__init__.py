"""Opinionated tooling around the abyss of LLMs."""

import importlib

from loguru import logger

from abyss.pipeline import Chain, Filter, FlatMap, Map, Predicate, Step, Take, collect, once
from abyss.search import DocumentSearcher, NotBlocked, Searcher
from abyss.steps import MinWords, Window
from abyss.types import Chunk

# Names whose modules pull in heavy or optional deps (httpx, pydantic): imported on first access.
_LAZY = {
    "SearxngSearcher": "abyss.search.searxng",
    "Settings": "abyss.settings",
}

__all__ = [
    "Chain", "Chunk", "DocumentSearcher", "Filter", "FlatMap", "Map", "MinWords", "NotBlocked", "Predicate",
    "Searcher", "Step", "Take", "Window", "collect", "once", *_LAZY,
]  # fmt: skip


def __getattr__(name: str):
    if name in _LAZY:
        return getattr(importlib.import_module(_LAZY[name]), name)
    raise AttributeError(f"module 'abyss' has no attribute {name!r}")


logger.disable("abyss")  # a library stays quiet; apps call logger.enable("abyss")
