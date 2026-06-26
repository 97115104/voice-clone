#!/usr/bin/env bash
# Voice Clone — deploy-locally.sh
# Supports: macOS (arm64/x86_64) · Linux
# Usage:  ./deploy-locally.sh

set -euo pipefail
IFS=$'\n\t'

# ─────────────────────────────────────────────────────────────────────────────
# Terminal colours + helpers
# ─────────────────────────────────────────────────────────────────────────────
B=$'\033[1m'; R=$'\033[0m'
RED=$'\033[0;31m'; GRN=$'\033[0;32m'; YLW=$'\033[0;33m'
CYN=$'\033[0;36m'; LIME=$'\033[38;5;154m'; GRY=$'\033[0;90m'

log()     { printf "${GRY}[VC]${R} %s\n" "$*"; }
ok()      { printf " ${GRN}✓${R}  %s\n" "$*"; }
warn()    { printf " ${YLW}⚠${R}  %s\n" "$*"; }
die()     { printf " ${RED}✗${R}  %s\n" "$*" >&2; exit 1; }
section() { printf "\n${B}${LIME}▶ %s${R}\n" "$*"; }
hr()      { printf "${GRY}──────────────────────────────────────────────────────────${R}\n"; }

spin() {
  local pid=$1 msg=${2:-working}
  local -a frames=("⣾" "⣽" "⣻" "⢿" "⡿" "⣟" "⣯" "⣷")
  local i=0
  while kill -0 "$pid" 2>/dev/null; do
    printf "\r   ${CYN}%s${R}  %s…" "${frames[$((i % 8))]}" "$msg"
    sleep 0.1; ((i++)) || true
  done
  printf "\r   ${GRN}✓${R}  %-60s\n" "$msg"
}

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PORT:-8004}"

ACTION="deploy"
OPEN_BROWSER=1
FORCE_BUILD=0
SKIP_BUILD=0
DETACH=0

COMPOSE_CMD=()
COMPOSE_FILES=(-f "$ROOT/docker-compose.yml")
GPU_MODE="cpu"
GPU_NAME="CPU"

# ─────────────────────────────────────────────────────────────────────────────
# Banner
# ─────────────────────────────────────────────────────────────────────────────
print_banner() {
  printf "\n${B}${LIME}"
  printf "  ╔══════════════════════════════════════════╗\n"
  printf "  ║           VOICE  CLONE  v1.0             ║\n"
  printf "  ║     Chatterbox voice cloning locally     ║\n"
  printf "  ║        All services run in Docker        ║\n"
  printf "  ╚══════════════════════════════════════════╝${R}\n\n"
}

usage() {
  cat <<'EOF'
Usage:
  ./deploy-locally.sh              Start via Docker (build image if missing)
  ./deploy-locally.sh --stop       Stop Docker services
  ./deploy-locally.sh --build      Force image rebuild
  ./deploy-locally.sh --no-build   Skip build even if image is missing
  ./deploy-locally.sh --detach     Exit after start (container keeps running)
  ./deploy-locally.sh --no-open    Do not open a browser tab

Environment:
  PORT=8004
  USE_GPU=1|0         Force GPU overlay on/off (Linux only)
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --stop) ACTION="stop" ;;
      --build) FORCE_BUILD=1 ;;
      --no-build) SKIP_BUILD=1 ;;
      --detach|-d) DETACH=1 ;;
      --no-open) OPEN_BROWSER=0 ;;
      --help|-h) usage; exit 0 ;;
      *) die "Unknown option: $1" ;;
    esac
    shift
  done
}

# ─────────────────────────────────────────────────────────────────────────────
# OS detection
# ─────────────────────────────────────────────────────────────────────────────
OS=""
ARCH=""

detect_os() {
  ARCH=$(uname -m)
  case "$(uname -s)" in
    Darwin) OS="macos" ;;
    Linux)  OS="linux" ;;
    *) die "Unsupported OS: $(uname -s). macOS and Linux only." ;;
  esac
  log "Platform: ${B}$OS${R} · ${B}$ARCH${R}"
}

# ─────────────────────────────────────────────────────────────────────────────
# GPU / compose file selection
# ─────────────────────────────────────────────────────────────────────────────
docker_gpu_available() {
  command -v nvidia-smi >/dev/null 2>&1 || return 1
  nvidia-smi >/dev/null 2>&1 || return 1
  docker info 2>/dev/null | grep -qiE 'nvidia|cdi:.*gpu'
}

select_gpu_mode() {
  section "Selecting runtime"

  if [[ -n "${USE_GPU:-}" ]]; then
    if [[ "$USE_GPU" == "1" || "$USE_GPU" == "true" ]]; then
      [[ "$OS" == "macos" ]] && die "GPU mode is not available on macOS Docker"
      docker_gpu_available || die "USE_GPU=1 but NVIDIA Docker runtime not available"
      GPU_MODE="gpu"
      COMPOSE_FILES+=(-f "$ROOT/docker-compose.gpu.yml")
      GPU_NAME="NVIDIA GPU (forced)"
      ok "Runtime: CUDA in Docker (forced)"
      return 0
    fi
    GPU_MODE="cpu"
    GPU_NAME="CPU (forced)"
    ok "Runtime: CPU in Docker (forced)"
    return 0
  fi

  if [[ "$OS" == "macos" ]]; then
    GPU_MODE="cpu"
    GPU_NAME="Apple Silicon (Docker — CPU inference)"
    ok "Runtime: CPU in Docker (macOS has no GPU passthrough)"
    return 0
  fi

  if docker_gpu_available; then
    local gpu_name vram_mb
    gpu_name=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo "NVIDIA GPU")
    vram_mb=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 || echo 0)
    GPU_MODE="gpu"
    COMPOSE_FILES+=(-f "$ROOT/docker-compose.gpu.yml")
    GPU_NAME="$gpu_name ($(( vram_mb / 1024 ))GB VRAM)"
    ok "Runtime: CUDA in Docker · ${B}$gpu_name${R}"
    return 0
  fi

  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    warn "NVIDIA GPU detected but Docker GPU runtime unavailable — using CPU"
  fi
  GPU_MODE="cpu"
  GPU_NAME="None (CPU mode)"
  ok "Runtime: CPU in Docker"
}

# ─────────────────────────────────────────────────────────────────────────────
# Docker helpers
# ─────────────────────────────────────────────────────────────────────────────
resolve_docker() {
  command -v docker >/dev/null 2>&1 && return 0
  [[ "$OS" == "macos" && -x "/Applications/Docker.app/Contents/Resources/bin/docker" ]] || return 1
  export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
}

detect_compose() {
  resolve_docker || die "Docker is required. Install Docker Desktop (macOS) or docker.io (Linux)."
  docker info >/dev/null 2>&1 || die "Docker is not running. Start Docker Desktop / dockerd."

  if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD=(docker-compose)
  else
    die "docker compose not found. Install docker-compose-plugin."
  fi
  ok "Docker is running"
}

compose() {
  "${COMPOSE_CMD[@]}" "${COMPOSE_FILES[@]}" "$@"
}

image_exists() {
  docker image inspect "voice-clone:${GPU_MODE}" >/dev/null 2>&1
}

# Show labelled progress while a background job runs; stream log file lines.
progress_job() {
  local pid=$1 label=$2 log_file="${3:-}"
  local -a frames=("⣾" "⣽" "⣻" "⢿" "⡿" "⣟" "⣯" "⣷")
  local i=0 last_line=""
  while kill -0 "$pid" 2>/dev/null; do
    if [[ -n "$log_file" && -f "$log_file" ]]; then
      last_line=$(tail -n 1 "$log_file" 2>/dev/null | sed 's/^[[:space:]]*//' | cut -c1-70)
      [[ -z "$last_line" ]] && last_line="$label"
    else
      last_line="$label"
    fi
    printf "\r   ${CYN}%s${R}  %s" "${frames[$((i % 8))]}" "$last_line"
    sleep 0.2; ((i++)) || true
  done
  printf "\r   ${GRN}✓${R}  %-72s\n" "$label"
}

build_image() {
  log "Building image voice-clone:${GPU_MODE} (first run: 5–15 min — pulling base + installing deps)"
  local _build_log; _build_log=$(mktemp)
  compose build --progress=plain >"$_build_log" 2>&1 &
  local _build_pid=$!
  progress_job $_build_pid "Building Docker image" "$_build_log"
  if ! wait $_build_pid; then
    printf "\n${RED}── Docker build failed ──${R}\n"
    tail -n 40 "$_build_log" >&2
    rm -f "$_build_log"
    die "Build failed — see output above"
  fi
  rm -f "$_build_log"
  ok "Image voice-clone:${GPU_MODE} built"
}

container_status() {
  compose ps --format '{{.State}}' voice-clone 2>/dev/null | head -1 || true
}

container_crashed() {
  local st
  st=$(container_status)
  [[ "$st" == "exited" || "$st" == "restarting" ]]
}

show_container_logs() {
  printf "\n${RED}── Container logs (last 60 lines) ──${R}\n"
  compose logs --tail 60 voice-clone 2>&1 || true
  printf "${RED}────────────────────────────────────${R}\n"
}

interpret_log_line() {
  local line="$1"
  if [[ "$line" == *"Downloading"* || "$line" == *"safetensors"* ]]; then
    printf "Downloading model weights"
  elif [[ "$line" == *"loading model"* || "$line" == *"Loading weights"* ]]; then
    printf "Loading model into memory"
  elif [[ "$line" == *"Uvicorn running"* || "$line" == *"Application startup complete"* ]]; then
    printf "Web server started"
  elif [[ "$line" == *"model loaded"* || "$line" == *"model ready"* ]]; then
    printf "Model ready"
  elif [[ "$line" == *"Error"* || "$line" == *"Traceback"* || "$line" == *"ModuleNotFoundError"* ]]; then
    printf "ERROR — see logs below"
  elif [[ "$line" == *"chatterbox"* ]]; then
    printf "Starting Chatterbox"
  else
    printf "Starting container"
  fi
}

wait_for_container() {
  local url="http://127.0.0.1:$PORT/live"
  local attempts=120 i st phase last_log=""
  log "Waiting for container to respond on ${url}"

  for ((i = 1; i <= attempts; i++)); do
    if container_crashed; then
      show_container_logs
      die "Container crashed during startup — fix errors above and run: ./deploy-locally.sh --build"
    fi

    last_log=$(compose logs --tail 1 voice-clone 2>/dev/null | sed 's/^[^|]*| //' | tail -1)
    phase=$(interpret_log_line "$last_log")
    printf "\r   ${CYN}▸${R}  [%3ds] %s — %s" "$((i / 2))" "$phase" "${last_log:0:50}"

    if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
      printf "\n"
      ok "Container responding"
      return 0
    fi

    if [[ "$last_log" == *"Traceback"* || "$last_log" == *"RuntimeError"* || "$last_log" == *"ModuleNotFoundError"* ]]; then
      printf "\n"
      show_container_logs
      die "Container failed during startup"
    fi

    sleep 0.5
  done

  printf "\n"
  show_container_logs
  die "Container did not respond within 60s"
}

open_browser() {
  local url="http://127.0.0.1:$PORT"
  case "$OS" in
    macos) open "$url" >/dev/null 2>&1 || true ;;
    *)     command -v xdg-open >/dev/null 2>&1 && xdg-open "$url" >/dev/null 2>&1 || true ;;
  esac
}

# ─────────────────────────────────────────────────────────────────────────────
# Start / stop
# ─────────────────────────────────────────────────────────────────────────────
start_studio() {
  section "Starting Voice Clone"

  detect_compose
  cd "$ROOT"
  export PORT

  if [[ "$SKIP_BUILD" != "1" ]]; then
    if [[ "$FORCE_BUILD" == "1" ]] || ! image_exists; then
      build_image
    else
      ok "Image voice-clone:${GPU_MODE} exists (use --build to rebuild)"
    fi
  else
    ok "Skipping build (--no-build)"
  fi

  log "Starting container voice-clone:${GPU_MODE} on http://127.0.0.1:$PORT"
  compose up -d voice-clone

  wait_for_container

  [[ "$OPEN_BROWSER" == "1" ]] && open_browser
  ok "Web UI → http://127.0.0.1:$PORT"
  log "Model download/load progress is shown in the browser (first run ~3 GB)"
}

stop_studio() {
  section "Stopping Voice Clone"
  if ! resolve_docker 2>/dev/null || ! docker info >/dev/null 2>&1; then
    ok "Docker not running — nothing to stop"
    return 0
  fi
  if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD=(docker-compose)
  else
    ok "docker compose not found — nothing to stop"
    return 0
  fi
  "${COMPOSE_CMD[@]}" -f "$ROOT/docker-compose.yml" -f "$ROOT/docker-compose.gpu.yml" down 2>/dev/null \
    || "${COMPOSE_CMD[@]}" -f "$ROOT/docker-compose.yml" down 2>/dev/null \
    || true
  ok "Stopped"
}

print_summary() {
  printf "\n"; hr; printf "\n"
  printf "  ${B}${LIME}Voice Clone is running!${R}\n\n"
  printf "  ${B}Web UI${R}  →  ${CYN}http://127.0.0.1:$PORT${R}\n"
  printf "  ${GRY}Runtime: $GPU_MODE · $GPU_NAME${R}\n"
  printf "  ${GRY}Model download progress is shown in the browser.${R}\n\n"
  hr
  printf "\n  ${GRY}Stop with ${B}./deploy-locally.sh --stop${R}${GRY}.${R}\n\n"
}

# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
main() {
  parse_args "$@"
  command -v curl >/dev/null 2>&1 || die "curl is required"

  case "$ACTION" in
    stop)
      detect_os
      stop_studio
      ;;
    deploy)
      print_banner
      detect_os
      select_gpu_mode
      start_studio
      print_summary
      ;;
  esac
}

main "$@"
