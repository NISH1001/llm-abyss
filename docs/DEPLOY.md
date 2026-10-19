# Deploying locally

How to run a local LLM with web search: SearXNG for search, llama.cpp's `llama-server` for the model and
its web UI, and abyss as the tool in between. Everything runs on one machine and is reachable from your
other devices over a private network such as Tailscale.

```
browser / phone ──HTTP──> llama-server :4242  (web UI + OpenAI-compatible API)
                              │ spawns per tool call (MCP over stdio)
                              v
                          abyss-mcp ──HTTP──> SearXNG :4243 (Docker) ──> search engines
```

- **SearXNG** is a self-hosted metasearch engine. abyss calls its JSON API.
- **llama-server** serves the model, the chat UI and the OpenAI-compatible API, and runs MCP tools.
- **abyss-mcp** is started by llama-server as a child process when the model calls a tool. It exits after
  each call, so it costs nothing while idle. There is no MCP port.

## Requirements

- Docker with the compose plugin
- [uv](https://docs.astral.sh/uv/)
- llama.cpp built locally, with `llama-server` on your `PATH`
- tmux, used by the launch script
- a GGUF model, by default in `~/models`

Build llama.cpp natively on the machine that runs it. Prebuilt binaries can fall back to slower code
paths on older CPUs.

```bash
git clone --depth 1 https://github.com/ggml-org/llama.cpp && cd llama.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON
cmake --build build -j"$(nproc)" --target llama-server
ln -s "$PWD/build/bin/llama-server" ~/.local/bin/llama-server
```

## 1. Configure

```bash
git clone https://github.com/NISH1001/llm-abyss && cd llm-abyss
cp .env.example .env
sed -i "s/^SEARXNG_SECRET=.*/SEARXNG_SECRET=$(openssl rand -hex 32)/" .env
uv sync --extra mcp
```

Always sync with `--extra mcp`. A plain `uv sync` removes the MCP packages, and the tool then fails to start.

One `.env` configures all three pieces. Every value is optional, and `.env.example` lists the defaults.

| Group | Variables | Read by |
|---|---|---|
| SearXNG container | `SEARXNG_HOST`, `SEARXNG_PORT`, `SEARXNG_SECRET` | docker compose |
| abyss tools | `SEARXNG_URL`, `SEARCH_*`, `CRAWL_*`, `CHUNK_*` | `abyss.settings.Settings` |
| llama-server | `LLM_*` | `deploy/llm.sh` |

## 2. SearXNG

```bash
docker compose up -d                # start; restarts on boot
docker compose logs -f searxng      # logs
docker compose restart searxng      # after editing deploy/searxng/settings.yml
docker compose up -d                # after changing SEARXNG_* in .env
docker compose down                 # stop
```

Check that the JSON API answers:

```bash
curl -s "http://127.0.0.1:4243/search?q=test&format=json" | head -c 200; echo
```

`deploy/searxng/settings.yml` turns the JSON format on and the rate limiter off. That suits a private
instance. Turn the limiter back on before exposing SearXNG beyond machines you trust. Startup errors
about the `ahmia` and `torch` engines are harmless; those engines need Tor.

## 3. llama-server with the tools

```bash
deploy/llm.sh start      # starts in tmux, waits for health, lists tools
deploy/llm.sh status     # health and tool list
deploy/llm.sh logs 100   # last 100 lines
deploy/llm.sh attach     # live view; detach with Ctrl+b, then d
deploy/llm.sh restart    # after editing LLM_* in .env
deploy/llm.sh stop
```

| Variable | Default | Meaning |
|---|---|---|
| `LLM_MODEL` | `Qwen3-1.7B-Q4_K_M.gguf` | file name in `LLM_MODELS_DIR`, or an absolute path |
| `LLM_MODELS_DIR` | `$HOME/models` | where model files live |
| `LLM_HOST` | `127.0.0.1` | `0.0.0.0` to reach it from other devices |
| `LLM_PORT` | `4242` | |
| `LLM_THREADS` | `4` | use the number of physical cores |
| `LLM_CTX` | `4096` | context window in tokens |
| `LLM_REASONING` | `off` | thinking mode for models that have one |
| `LLM_CORS_ORIGINS` | localhost only | browser origins allowed to use the UI and API |
| `LLM_EXTRA_ARGS` | empty | any other llama-server flags |
| `LLM_SESSION` | `abyss-llm` | tmux session name |

A variable set on the command line wins over `.env` for that run, for example
`LLM_CTX=8192 deploy/llm.sh restart`.

The tools come from `deploy/mcp.json`. Each entry is one MCP server, and llama-server names its tools
`<server>_<tool>`. The stock entries run `.venv/bin/abyss-mcp web` and `.venv/bin/abyss-mcp kb`, whose
`search` tools appear as `web_search` and `kb_search`.

`kb_search` searches a Logseq graph: set `LOGSEQ_KB` in `.env` to the graph folder. It scans `pages/` and
`journals/` on every call (no index, about half a second for a few thousand pages once cached), drops stub
pages, keeps the best `CHUNK_TOP_K` pages and returns about 64 words around each match. Without `LOGSEQ_KB`
the `kb` entry fails at startup and llama-server serves the other tools. Keeping the graph in git works well:
clone it read-only on the server and `git pull` on a timer.
To serve your own tools, add an entry pointing at your script, as in the README's MCP example.

Changes to the abyss settings in `.env` apply on the next tool call with no restart, because llama-server
starts a fresh tool process for each call. Restart llama-server only when you change `LLM_*` variables or
add or remove tools.

### Check it

```bash
curl -s http://127.0.0.1:4242/health; echo                        # {"status":"ok"}
curl -s http://127.0.0.1:4242/tools | grep -o '"web_search"'       # tool registered
```

Open `http://127.0.0.1:4242`, enable `web_search` under Tools, and ask something current. The chat shows
the tool call and its result before the answer.

## 4. Other clients

**OpenAI-compatible API.** Any client that takes a custom base URL works. Use `http://<host>:4242/v1` and
any API key, or the key you set with `--api-key`. Tools only run automatically inside llama-server's own
web UI. An API client gets the model alone, and must bring its own tools.

**Other MCP clients.** Clients that start stdio servers, such as editors or coding agents, can run the
same tool themselves:

```bash
claude mcp add web -- /path/to/llm-abyss/.venv/bin/abyss-mcp
```

## 5. Reaching it from other devices

Both services bind to `127.0.0.1` by default. Pick one of the options below.

### Tailscale (recommended)

[Tailscale](https://tailscale.com) puts your devices on a private, encrypted network. Only devices signed
in to your tailnet can reach the server, and its address stays fixed.

1. Install Tailscale on the server and on each client device, and sign in to the same tailnet.
2. In `.env`, set `LLM_HOST=0.0.0.0` and, if you want the SearXNG page too, `SEARXNG_HOST=0.0.0.0`.
3. Allow the UI's origins. With MagicDNS on, a machine is reachable by its short name and its full name:

   ```bash
   LLM_CORS_ORIGINS=http://localhost:4242,http://127.0.0.1:4242,http://<machine>:4242,http://<machine>.<tailnet>.ts.net:4242
   ```

   Enabling MCP tools restricts browser origins to localhost unless you list them here. Without this, the
   UI loads on another device but can't talk to the server.
4. If a host firewall such as ufw blocks inbound traffic, allow the port on the Tailscale interface:

   ```bash
   sudo ufw allow in on tailscale0 to any port 4242 proto tcp
   ```

5. Apply the changes with `deploy/llm.sh restart` and `docker compose up -d`, then open
   `http://<machine>:4242` on the other device.

Find your machine's name and address with `tailscale status`. To bind to the Tailscale interface only,
use its `100.x.y.z` address as the host instead of `0.0.0.0`. The catch is that the service fails to start
if it comes up before Tailscale does.

### SSH tunnel

No extra software, one device at a time:

```bash
ssh -N -L 4242:127.0.0.1:4242 user@server
```

Then open `http://localhost:4242` on the client. The server keeps its localhost-only binding.

### Public tunnels and the open internet

llama-server and SearXNG have no user accounts. Don't expose them publicly as configured here. If you must,
put both behind an authenticating reverse proxy or tunnel, set `--api-key` through `LLM_EXTRA_ARGS`, and
turn the SearXNG limiter back on.

### Notes on binding to 0.0.0.0

- `0.0.0.0` means every interface, including your local network, not only Tailscale.
- **Docker-published ports bypass host firewalls like ufw.** With `SEARXNG_HOST=0.0.0.0`, SearXNG is
  reachable from your LAN whatever your firewall rules say.

## Performance on small machines

Tool results are prompt tokens, and on a CPU the prompt is usually the slow part.

- Keep `SEARCH_TOP_K` small. Five snippets are about 250 to 300 tokens.
- Set `LLM_THREADS` to physical cores. Hyperthreads don't help.
- Leave `LLM_REASONING=off` unless you need it. Thinking adds a long preamble before every answer.
- A 1.5B to 4B model at `Q4_K_M` is the practical range for 8 GB of RAM without a GPU.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| UI says "Server unavailable" | llama-server isn't running | `deploy/llm.sh status`, then `start` or check `logs` |
| `web_search` missing under Tools | MCP extra not installed, or started outside the repo | `uv sync --extra mcp`, then `deploy/llm.sh restart` |
| UI works on the server but not on other devices | origin not allowed, or host bound to localhost | set `LLM_CORS_ORIGINS` and `LLM_HOST`, then restart |
| Tool returns an HTTP 403 error | SearXNG JSON format disabled | keep `json` under `search.formats` in `settings.yml` |
| Tool returns "No results." | engines blocked or timing out | `docker compose logs searxng`; raise `SEARCH_TIMEOUT` |
| `start` says "already running" | session exists | `deploy/llm.sh status`, or `stop` first |
| Address already in use | another process on the port | `ss -ltnp \| grep 4242` and stop it |
