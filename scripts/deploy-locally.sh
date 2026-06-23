#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVER_DIR="$ROOT/server"
VENV_DIR="$ROOT/.venv"
RUNTIME_DIR="$ROOT/.runtime"

# shellcheck source=scripts/install-deps.sh
source "$ROOT/scripts/install-deps.sh"

OS="$(uname -s)"
ACTION=""
OPEN_BROWSER="${OPEN_BROWSER:-1}"
INSTALL_DEPS="${INSTALL_DEPS:-1}"
HOLD="${HOLD:-1}"
FORCE_PORTS="${FORCE_PORTS:-0}"

DEFAULT_PORT="${PORT:-8004}"
SERVER_PID=""

log() { printf "\n==> %s\n" "$*"; }
ok() { printf "[+] %s\n" "$*"; }
warn() { printf "[!] %s\n" "$*" >&2; }
die() { printf "[x] %s\n" "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage:
  scripts/deploy-locally.sh          # install deps, start server, open browser
  scripts/deploy-locally.sh --stop   # stop local server

Options:
  --no-install   Skip pip installs (reuse existing .venv)
  --no-open      Do not open a browser tab
  --smoke        Start server, wait for /health, then exit
  --help         Show this help

Environment:
  PORT=8004              Server port
  OPEN_BROWSER=0         Same as --no-open
  INSTALL_DEPS=0         Same as --no-install
  HOLD=0                 Exit after startup (no "press Enter to stop")
  TTS_DEVICE=cuda|cpu    Override inference device
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --stop) ACTION="stop" ;;
      --no-install) INSTALL_DEPS=0 ;;
      --no-open) OPEN_BROWSER=0 ;;
      --smoke) ACTION="smoke"; HOLD=0; OPEN_BROWSER=0 ;;
      --help|-h) usage; exit 0 ;;
      *) die "Unknown option: $1" ;;
    esac
    shift
  done
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "$1 is required"
}

port_pids() {
  lsof -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null || true
}

port_busy() {
  [[ -n "$(port_pids "$1")" ]]
}

pick_port() {
  local port="$1"
  if [[ "$FORCE_PORTS" == "1" && -n "$(port_pids "$port")" ]]; then
    warn "Port $port is in use; FORCE_PORTS=1 so stopping listeners"
    kill $(port_pids "$port") 2>/dev/null || true
    sleep 1
  fi
  while port_busy "$port"; do
    warn "Port $port is in use; trying $((port + 1))"
    port=$((port + 1))
  done
  printf "%s" "$port"
}

open_url() {
  [[ "$OPEN_BROWSER" == "1" ]] || return 0
  local url="$1"
  if [[ "$OS" == "Darwin" ]]; then
    open "$url" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" >/dev/null 2>&1 || true
  fi
}

wait_http() {
  local url="$1"
  local label="$2"
  local attempts="${3:-1200}"
  local pid="${4:-}"
  for i in $(seq 1 "$attempts"); do
    if [[ -n "$pid" ]] && ! kill -0 "$pid" 2>/dev/null; then
      warn "$label process exited before becoming ready"
      return 1
    fi
    if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
      ok "$label ready"
      return 0
    fi
    if (( i % 10 == 0 )); then
      printf "    waiting for %s (%ds)...\n" "$label" "$((i / 2))"
      if [[ -f "$RUNTIME_DIR/server.log" ]]; then
        tail -n 3 "$RUNTIME_DIR/server.log" 2>/dev/null | sed 's/^/      /'
      fi
    fi
    sleep 0.5
  done
  return 1
}

install_deps() {
  [[ "$INSTALL_DEPS" == "1" ]] || return 0
  WITH_MODEL=0 install_all
}

deps_ready() {
  [[ -x "$VENV_DIR/bin/python" ]] || return 1
  "$VENV_DIR/bin/python" -c "
import torch, chatterbox, fastapi, uvicorn, soundfile
import perth
assert perth.PerthImplicitWatermarker is not None, 'resemble-perth broken (check setuptools<82)'
" >/dev/null 2>&1
}

ensure_deps() {
  ensure_setuptools_compat
  if deps_ready; then
    ok "Dependencies already installed"
    ensure_venv
    return 0
  fi
  install_deps
}

start_server() {
  mkdir -p "$RUNTIME_DIR"
  PORT="$(pick_port "${PORT:-$DEFAULT_PORT}")"
  export PORT

  log "Starting voice clone server on http://127.0.0.1:$PORT"
  log "Loading Chatterbox model — CPU can take 5–10 min; GPU is much faster"
  (
    cd "$SERVER_DIR"
    export PYTHONUNBUFFERED=1
    "$VENV_DIR/bin/python" tts_server.py
  ) >"$RUNTIME_DIR/server.log" 2>&1 &
  SERVER_PID=$!

  if ! wait_http "http://127.0.0.1:$PORT/health" "Voice clone server" 1200 "$SERVER_PID"; then
    warn "Server log (last 80 lines):"
    tail -n 80 "$RUNTIME_DIR/server.log" >&2 || true
    die "Server did not become healthy"
  fi

  if ! wait_http "http://127.0.0.1:$PORT/" "Web UI" 40; then
    warn "Server log (last 80 lines):"
    tail -n 80 "$RUNTIME_DIR/server.log" >&2 || true
    die "Web UI did not load"
  fi

  ok "Web UI: http://127.0.0.1:$PORT"
  ok "Logs:   $RUNTIME_DIR/server.log"
}

stop_local() {
  log "Stopping local voice clone server"
  local port="${PORT:-$DEFAULT_PORT}"
  local pids
  pids="$(port_pids "$port")"
  if [[ -n "$pids" ]]; then
    kill $pids 2>/dev/null || true
    ok "Stopped listener on port $port"
  else
    ok "No server listening on port $port"
  fi
}

cleanup() {
  [[ -n "${SERVER_PID:-}" ]] && kill "$SERVER_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

hold_open() {
  echo ""
  echo "========================================="
  echo "  Voice clone: http://127.0.0.1:${PORT:-$DEFAULT_PORT}"
  echo "  Logs:        $RUNTIME_DIR/server.log"
  echo "  Stop:        scripts/deploy-locally.sh --stop"
  echo "  Press Enter to stop this local session."
  echo "========================================="
  read -r || true
  HOLD=0
  cleanup
}

run_deploy() {
  need_cmd curl
  mkdir -p "$RUNTIME_DIR"

  ensure_ffmpeg
  ensure_deps
  start_server
  open_url "http://127.0.0.1:${PORT:-$DEFAULT_PORT}"

  if [[ "$HOLD" == "1" ]]; then
    trap - EXIT INT TERM
    hold_open
    stop_local
  else
    ok "Smoke deploy complete"
    trap - EXIT
  fi
}

main() {
  parse_args "$@"

  case "${ACTION:-deploy}" in
    stop) stop_local ;;
    smoke) run_deploy ;;
    deploy) run_deploy ;;
    *) die "Unknown action: $ACTION" ;;
  esac
}

main "$@"
