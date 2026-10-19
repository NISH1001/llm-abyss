from abyss.search._base import BLOCKED_DOMAINS, NotBlocked, Searcher, is_blocked

__all__ = ["BLOCKED_DOMAINS", "NotBlocked", "Searcher", "SearxngSearcher", "is_blocked"]


def __getattr__(name: str):  # lazy: SearxngSearcher imports httpx
    if name == "SearxngSearcher":
        from abyss.search.searxng import SearxngSearcher

        return SearxngSearcher
    raise AttributeError(name)
