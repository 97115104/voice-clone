#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib/common.sh
source "$ROOT/scripts/lib/common.sh"

MODE="${MODE:-auto}"
ACTION="deploy"
DEPLOY_EXTRA=()

usage() {
  cat <<'EOF'
Usage:
  ./scripts/deploy.sh              Auto: Docker if running, else local Python
  ./scripts/deploy.sh --docker     Force Docker
  ./scripts/deploy.sh --local      Force local Python
  ./scripts/deploy.sh --stop       Stop Docker + local server
  ./scripts/deploy.sh --smoke      Health-check then exit (local only)
  ./scripts/deploy.sh --detach     Docker: run in background
  ./scripts/deploy.sh --no-build   Docker: skip image build

Works on macOS, Linux, and Windows (Git Bash / WSL).
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --docker) MODE="docker" ;;
      --local) MODE="local" ;;
      --stop) ACTION="stop" ;;
      --smoke) ACTION="smoke" ;;
      --no-open) export OPEN_BROWSER=0 ;;
      --no-install) export INSTALL_DEPS=0 ;;
      --detach|-d) DEPLOY_EXTRA+=(--detach) ;;
      --no-build) DEPLOY_EXTRA+=(--no-build) ;;
      --help|-h) usage; exit 0 ;;
      *) vc_die "Unknown option: $1" ;;
    esac
    shift
  done
}

resolve_deploy_mode() {
  [[ "$MODE" != "auto" ]] && return 0
  if vc_should_prefer_local && [[ -x "$VC_VENV_DIR/bin/python" || -x "$VC_VENV_DIR/Scripts/python.exe" ]]; then
    MODE="local"
    vc_ok "Deploy mode: local (GPU/MPS on host)"
  elif vc_docker_running; then
    MODE="docker"
    vc_ok "Deploy mode: docker"
  else
    MODE="local"
    vc_ok "Deploy mode: local"
  fi
}

run_deploy_docker() {
  if ((${#DEPLOY_EXTRA[@]} > 0)); then
    exec "$ROOT/scripts/deploy-docker.sh" "${DEPLOY_EXTRA[@]}"
  else
    exec "$ROOT/scripts/deploy-docker.sh"
  fi
}

main() {
  parse_args "$@"
  case "$ACTION" in
    stop)
      "$ROOT/scripts/deploy-docker.sh" --stop || true
      PORT="${PORT:-8004}" "$ROOT/scripts/deploy-locally.sh" --stop || true
      ;;
    smoke)
      PORT="${PORT:-8004}" "$ROOT/scripts/deploy-locally.sh" --smoke
      ;;
    deploy)
      resolve_deploy_mode
      if [[ "$MODE" == "docker" ]]; then
        run_deploy_docker
      else
        if ! vc_docker_running && vc_resolve_docker >/dev/null 2>&1; then
          vc_warn "Docker installed but not running — using local Python"
        fi
        exec "$ROOT/scripts/deploy-locally.sh"
      fi
      ;;
  esac
}

main "$@"
