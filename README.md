# llm-abyss

Opinionated tooling around the abyss of LLMs: composable, async-first retrieval steps, servable as MCP tools.

## Run locally

```bash
cp .env.example .env              # then set SEARXNG_SECRET (openssl rand -hex 32)
uv sync --extra mcp               # always with --extra mcp, or the tool can't start
docker compose up -d              # SearXNG on :4243
deploy/llm.sh start               # llama-server in tmux on :4242, with the web_search tool
deploy/llm.sh status | logs | attach | restart | stop
```

MCP runs over stdio: llama-server spawns `.venv/bin/abyss-mcp` itself (see `deploy/mcp.json`), so there is
no MCP port. Any other MCP client can spawn the same command.
