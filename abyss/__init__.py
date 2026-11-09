"""Opinionated tooling around the abyss of LLMs."""

__version__ = "0.1.1"

import importlib

from loguru import logger

from abyss.pipeline import Chain, Filter, FlatMap, Map, Predicate, Step, Take, collect, once
from abyss.search import DocumentSearch, NotBlocked, Search
from abyss.steps import MinWords, Window
from abyss.types import Chunk

# Names whose modules pull in heavy or optional deps (httpx, pydantic): imported on first access.
_LAZY = {
    "SearxngSearch": "abyss.search.searxng",
    "SemanticScholarSearch": "abyss.search.semantic_scholar",
    "Settings": "abyss.settings",
}

__all__ = [
    "Chain", "Chunk", "DocumentSearch", "Filter", "FlatMap", "Map", "MinWords", "NotBlocked", "Predicate",
    "Search", "Step", "Take", "Window", "collect", "once", *_LAZY,
]  # fmt: skip


def __getattr__(name: str):
    if name in _LAZY:
        return getattr(importlib.import_module(_LAZY[name]), name)
    raise AttributeError(f"module 'abyss' has no attribute {name!r}")


logger.disable("abyss")  # a library stays quiet; apps call logger.enable("abyss")
