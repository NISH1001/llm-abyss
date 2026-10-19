"""Project-level settings, read where components get assembled (the MCP server, scripts).
Components themselves take plain constructor arguments and never read Settings.

Env vars win over .env (read from the working directory); names are case-insensitive. Unknown keys are
ignored, so one .env can also hold the SearXNG and llama-server settings. Needs pydantic-settings
(in the [mcp] extra). Defaults are tuned for a small model on a CPU-only box: little context per call.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # search
    searxng_url: str = "http://127.0.0.1:4243"
    search_categories: str = "general"  # general | science
    search_timeout: float = 8.0  # seconds; SearXNG waits on several engines
    search_top_k: int = 5  # results kept per query

    # crawl (used once a crawler is in the pipeline)
    crawl_concurrency: int = 3  # pages fetched at once
    crawl_timeout: float = 6.0  # seconds per page
    crawl_max_bytes: int = 1_500_000  # stop reading a page past this

    # chunk + rank (used once a chunker and ranker are in the pipeline)
    chunk_size: int = 512  # approx tokens per chunk
    chunk_overlap: int = 64  # approx tokens shared by neighbouring chunks
    chunk_top_k: int = 3  # chunks returned to the model
