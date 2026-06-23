#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/common.sh
source "$ROOT/scripts/lib/common.sh"

OPEN_BROWSER="${OPEN_BROWSER:-1}"
BUILD="${BUILD:-1}"
DETACH="${DETACH:-0}"
PORT="${PORT:-8004}"

usage() {
  cat <<'EOF'
Usage:
  scripts/deploy-docker.sh            Build (if needed) and start via Docker
  scripts/deploy-docker.sh --stop     Stop Docker services
  scripts/deploy-docker.sh --no-build Skip image build
  scripts/deploy-docker.sh --detach   Run in background

Auto-detects NVIDIA GPU on Linux/Windows Docker. macOS Docker always uses CPU.

Environment:
  PORT=8004
  OPEN_BROWSER=0
  USE_GPU=1|0         Force GPU mode on/off
EOF
}

parse_args() {
  ACTION="up"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --stop) ACTION="stop" ;;
      --no-build) BUILD=0 ;;
      --detach|-d) DETACH=1 ;;
      --no-open) OPEN_BROWSER=0 ;;
      --help|-h) usage; exit 0 ;;
      *) vc_die "Unknown option: $1" ;;
    esac
    shift
  done
}

compose_up() {
  local compose_cmd gpu=0 files=(-f "$ROOT/docker-compose.yml")
  compose_cmd="$(vc_docker_compose_cmd)" || vc_die "docker compose is required"
  vc_docker_running || vc_die "Docker is not running. Start Docker Desktop / dockerd."

  vc_print_platform_summary

  if vc_detect_docker_gpu; then
    gpu=1
    files+=(-f "$ROOT/docker-compose.gpu.yml")
    vc_ok "Using NVIDIA GPU in Docker"
  else
    vc_ok "Using CPU in Docker"
  fi

  export PORT
  if [[ "$BUILD" == "1" ]]; then
    vc_log "Building Docker image"
    $compose_cmd "${files[@]}" build
  fi

  vc_log "Starting voice clone on http://127.0.0.1:$PORT"
  if [[ "$DETACH" == "1" ]]; then
    $compose_cmd "${files[@]}" up -d
    vc_wait_http "http://127.0.0.1:$PORT/health" "Voice clone server" 1200 "" || {
      $compose_cmd "${files[@]}" logs --tail 80
      vc_die "Server did not become healthy"
    }
  else
    vc_warn "First start downloads the model — CPU can take 5–15 min"
    vc_warn "Press Ctrl+C to stop"
    [[ "$OPEN_BROWSER" == "1" ]] && (
      vc_wait_http "http://127.0.0.1:$PORT/" "Loading page" 120 "" &&
      vc_open_url "http://127.0.0.1:$PORT"
    ) &
    $compose_cmd "${files[@]}" up
  fi

  if [[ "$DETACH" == "1" && "$OPEN_BROWSER" == "1" ]]; then
    vc_open_url "http://127.0.0.1:$PORT"
  fi
  vc_ok "Web UI: http://127.0.0.1:$PORT"
}

compose_down() {
  local compose_cmd
  compose_cmd="$(vc_docker_compose_cmd)" || vc_die "docker compose is required"
  vc_log "Stopping Docker services"
  $compose_cmd -f "$ROOT/docker-compose.yml" -f "$ROOT/docker-compose.gpu.yml" down 2>/dev/null \
    || $compose_cmd -f "$ROOT/docker-compose.yml" down
  vc_ok "Stopped"
}

main() {
  parse_args "$@"
  mkdir -p "$ROOT/.runtime"
  case "$ACTION" in
    up) compose_up ;;
    stop) compose_down ;;
  esac
}

main "$@"
