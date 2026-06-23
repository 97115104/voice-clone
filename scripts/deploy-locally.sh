#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/common.sh
source "$ROOT/scripts/lib/common.sh"
# shellcheck source=install-deps.sh
source "$ROOT/scripts/install-deps.sh"

ROOT="$VC_ROOT"
SERVER_DIR="$ROOT/server"
VENV_DIR="$VC_VENV_DIR"
RUNTIME_DIR="$VC_RUNTIME_DIR"

ACTION=""
OPEN_BROWSER="${OPEN_BROWSER:-1}"
INSTALL_DEPS="${INSTALL_DEPS:-1}"
HOLD="${HOLD:-1}"
FORCE_PORTS="${FORCE_PORTS:-0}"
DEFAULT_PORT="${PORT:-8004}"
SERVER_PID=""

log() { vc_log "$@"; }
ok() { vc_ok "$@"; }
warn() { vc_warn "$@"; }
die() { vc_die "$@"; }

usage() {
  cat <<'EOF'
Usage:
  scripts/deploy-locally.sh          Install deps, start local server, open browser
  scripts/deploy-locally.sh --stop   Stop local server

Options:
  --no-install   Skip pip installs (reuse existing .venv)
  --no-open      Do not open a browser tab
  --smoke        Start server, wait for /health, then exit
  --help         Show this help

Environment:
  PORT=8004
  TTS_DEVICE=cuda|mps|cpu   Override inference device (auto-detected by default)
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

install_deps() {
  [[ "$INSTALL_DEPS" == "1" ]] || return 0
  WITH_MODEL=0
  install_local
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
  local py device
  py="$VENV_DIR/bin/python"
  [[ -x "$py" ]] || py="$VENV_DIR/Scripts/python.exe"

  mkdir -p "$RUNTIME_DIR"
  PORT="$(vc_pick_port "${PORT:-$DEFAULT_PORT}")"
  export PORT
  device="$(vc_detect_host_device)"
  export TTS_DEVICE="$device"

  log "Starting voice clone server on http://127.0.0.1:$PORT (device: $device)"
  if [[ "$device" == "cpu" ]]; then
    log "Loading Chatterbox model — CPU can take 5–10 min on first start"
  fi

  (
    cd "$SERVER_DIR"
    export PYTHONUNBUFFERED=1
    "$py" tts_server.py
  ) >"$RUNTIME_DIR/server.log" 2>&1 &
  SERVER_PID=$!

  if ! vc_wait_http "http://127.0.0.1:$PORT/health" "Voice clone server" 1200 "$SERVER_PID" "$RUNTIME_DIR/server.log"; then
    warn "Server log (last 80 lines):"
    tail -n 80 "$RUNTIME_DIR/server.log" >&2 || true
    die "Server did not become healthy"
  fi

  if ! vc_wait_http "http://127.0.0.1:$PORT/" "Web UI" 40 "" "$RUNTIME_DIR/server.log"; then
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
  pids="$(vc_port_pids "$port")"
  if [[ -n "$pids" ]]; then
    # shellcheck disable=SC2046
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
  vc_need_cmd curl
  mkdir -p "$RUNTIME_DIR"
  vc_print_platform_summary
  ensure_ffmpeg
  ensure_deps
  start_server
  [[ "$OPEN_BROWSER" == "1" ]] && vc_open_url "http://127.0.0.1:${PORT:-$DEFAULT_PORT}"

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
    smoke|deploy) run_deploy ;;
    *) die "Unknown action: $ACTION" ;;
  esac
}

main "$@"
