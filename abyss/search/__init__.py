import importlib

from abyss.search._base import BLOCKED_DOMAINS, NotBlocked, Search, is_blocked
from abyss.search.documents import DocumentSearch

_LAZY = {"SearxngSearch": "abyss.search.searxng"}  # imports httpx

__all__ = ["BLOCKED_DOMAINS", "DocumentSearch", "NotBlocked", "Search", "is_blocked", *_LAZY]


def __getattr__(name: str):
    if name in _LAZY:
        return getattr(importlib.import_module(_LAZY[name]), name)
    raise AttributeError(f"module 'abyss.search' has no attribute {name!r}")
