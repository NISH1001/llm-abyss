"""Defaults for the stock tools. Each field can be overridden by an env var of the same name in upper case
(SEARXNG_URL, SEARCH_TOP_K, ...). Fields for crawling and ranking get added with those components."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True)
class Config:
    searxng_url: str = "http://127.0.0.1:4243"
    search_categories: str = "general"
    search_timeout: float = 8.0
    search_top_k: int = 5

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        env = os.environ if env is None else env
        overrides = {
            f.name: type(f.default)(env[f.name.upper()]) for f in fields(cls) if f.name.upper() in env
        }
        return cls(**overrides)
