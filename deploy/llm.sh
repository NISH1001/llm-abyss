#!/usr/bin/env bash
# llama-server in a tmux session, configured from .env. MCP tools come from deploy/mcp.json.
# Usage: deploy/llm.sh start | stop | restart | status | attach | logs
set -euo pipefail
cd "$(dirname "$0")/.."
# Load .env without overriding variables already set (so `LLM_PORT=4299 deploy/llm.sh start` wins).
if [[ -f .env ]]; then
  while IFS='=' read -r key value; do
    [[ $key =~ ^[A-Za-z_][A-Za-z0-9_]*$ && -z ${!key+x} ]] || continue
    value=${value%%[[:space:]]#*}             # drop inline comment
    value=${value%"${value##*[![:space:]]}"}  # drop trailing spaces
    export "$key=$value"
  done < .env
fi

SESSION=${LLM_SESSION:-abyss-llm}
MODELS_DIR=${LLM_MODELS_DIR:-$HOME/models}
MODEL=${LLM_MODEL:-Qwen3-1.7B-Q4_K_M.gguf}
[[ $MODEL == /* ]] || MODEL="$MODELS_DIR/$MODEL"
PORT=${LLM_PORT:-4242}
CMD=(
  llama-server -m "$MODEL"
  -t "${LLM_THREADS:-4}" -c "${LLM_CTX:-4096}" --reasoning "${LLM_REASONING:-off}"
  --host "${LLM_HOST:-127.0.0.1}" --port "$PORT"
  --mcp-servers-config deploy/mcp.json
  --cors-origins "${LLM_CORS_ORIGINS:-http://localhost:$PORT,http://127.0.0.1:$PORT}"
)

running() { tmux has-session -t "$SESSION" 2>/dev/null; }

start() {
  running && { echo "already running (tmux session '$SESSION')"; return 0; }
  [[ -f $MODEL ]] || { echo "model not found: $MODEL" >&2; exit 1; }
  [[ -x .venv/bin/abyss-mcp ]] || { echo "missing .venv/bin/abyss-mcp: run 'uv sync --extra mcp'" >&2; exit 1; }
  tmux new-session -d -s "$SESSION" -c "$PWD" "$(printf '%q ' "${CMD[@]}"); echo; echo 'llama-server exited'; read -r"
  echo "started '$SESSION': $(basename "$MODEL") on ${LLM_HOST:-127.0.0.1}:$PORT"
  echo "waiting for health..."
  for _ in $(seq 1 90); do curl -sf -m 2 "http://127.0.0.1:$PORT/health" >/dev/null && { status; return 0; }; sleep 1; done
  echo "not healthy after 90s; check: $0 logs" >&2; exit 1
}

stop() { running && tmux kill-session -t "$SESSION" && echo "stopped '$SESSION'" || echo "not running"; }

status() {
  running || { echo "not running"; return 1; }
  echo "session: $SESSION | model: $(basename "$MODEL") | port: $PORT"
  if ! curl -sf -m 3 "http://127.0.0.1:$PORT/health" >/dev/null; then
    echo "health:  unreachable (server exited? see: $0 logs)"; return 1
  fi
  echo "health:  ok"
  echo "tools:   $(curl -s -m 3 "http://127.0.0.1:$PORT/tools" | grep -o '"tool":"[^"]*"' | cut -d'"' -f4 | paste -sd, -)"
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  status) status ;;
  attach) exec tmux attach -t "$SESSION" ;;
  logs) tmux capture-pane -p -t "$SESSION" -S -"${2:-60}" ;;
  *) echo "usage: $0 start | stop | restart | status | attach | logs [lines]" >&2; exit 2 ;;
esac
