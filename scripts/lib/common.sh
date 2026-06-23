#!/usr/bin/env bash
# Shared helpers for voice-clone scripts (macOS, Linux, Git Bash/WSL on Windows).

# Guard against double-sourcing.
[[ -n "${VC_COMMON_SOURCED:-}" ]] && return 0
VC_COMMON_SOURCED=1

VC_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VC_VENV_DIR="$VC_ROOT/.venv"
VC_RUNTIME_DIR="$VC_ROOT/.runtime"

vc_log() { printf "\n==> %s\n" "$*"; }
vc_ok() { printf "[+] %s\n" "$*"; }
vc_warn() { printf "[!] %s\n" "$*" >&2; }
vc_die() { printf "[x] %s\n" "$*" >&2; exit 1; }

vc_detect_os() {
  case "$(uname -s)" in
    Darwin)  printf "darwin" ;;
    Linux)   printf "linux" ;;
    MINGW*|MSYS*|CYGWIN*) printf "windows" ;;
    *)       printf "unknown" ;;
  esac
}

vc_detect_arch() {
  uname -m
}

vc_is_windows() {
  [[ "$(vc_detect_os)" == "windows" ]]
}

vc_is_macos() {
  [[ "$(vc_detect_os)" == "darwin" ]]
}

vc_is_linux() {
  [[ "$(vc_detect_os)" == "linux" ]]
}

# Returns: cpu | cuda | mps
vc_detect_host_device() {
  if [[ -n "${TTS_DEVICE:-}" ]]; then
    printf "%s" "$TTS_DEVICE"
    return 0
  fi

  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    printf "cuda"
    return 0
  fi

  if vc_is_macos && [[ "$(vc_detect_arch)" == "arm64" ]]; then
    if [[ -x "$VC_VENV_DIR/bin/python" ]]; then
      if "$VC_VENV_DIR/bin/python" -c "import torch; print('yes' if torch.backends.mps.is_available() else 'no')" 2>/dev/null | grep -q yes; then
        printf "mps"
        return 0
      fi
    fi
    # Assume MPS likely on Apple Silicon even before venv exists
    printf "mps"
    return 0
  fi

  printf "cpu"
}

vc_torch_index_for_device() {
  local device="${1:-cpu}"
  case "$device" in
    cuda) printf "https://download.pytorch.org/whl/cu124" ;;
    *)    printf "https://download.pytorch.org/whl/cpu" ;;
  esac
}

vc_resolve_docker() {
  if command -v docker >/dev/null 2>&1; then
    printf "docker"
    return 0
  fi
  if vc_is_macos && [[ -x "/Applications/Docker.app/Contents/Resources/bin/docker" ]]; then
    export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
    printf "docker"
    return 0
  fi
  return 1
}

vc_docker_compose_cmd() {
  vc_resolve_docker >/dev/null || return 1
  if docker compose version >/dev/null 2>&1; then
    printf "docker compose"
    return 0
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    printf "docker-compose"
    return 0
  fi
  return 1
}

vc_docker_running() {
  vc_resolve_docker >/dev/null || return 1
  docker info >/dev/null 2>&1
}

# Docker GPU: Linux/Windows with NVIDIA container toolkit. Never on macOS Docker.
vc_detect_docker_gpu() {
  if [[ -n "${USE_GPU:-}" ]]; then
    [[ "$USE_GPU" == "1" || "$USE_GPU" == "true" ]]
    return
  fi
  if [[ "$(vc_detect_os)" == "darwin" ]]; then
    return 1
  fi
  vc_docker_running || return 1
  command -v nvidia-smi >/dev/null 2>&1 || return 1
  nvidia-smi >/dev/null 2>&1 || return 1
  # Check Docker can see NVIDIA runtime (lightweight)
  if docker info 2>/dev/null | grep -qiE 'nvidia|gpu'; then
    return 0
  fi
  # Fallback: try a tiny GPU probe (may pull image first time)
  if docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

vc_open_url() {
  local url="$1"
  local os
  os="$(vc_detect_os)"
  case "$os" in
    darwin)  open "$url" >/dev/null 2>&1 || true ;;
    windows) cmd //c start "" "$url" >/dev/null 2>&1 || powershell -NoProfile -Command "Start-Process '$url'" >/dev/null 2>&1 || true ;;
    *)       command -v xdg-open >/dev/null 2>&1 && xdg-open "$url" >/dev/null 2>&1 || true ;;
  esac
}

vc_port_pids() {
  local port="$1"
  if vc_is_windows; then
    netstat -ano 2>/dev/null | awk -v p=":$port" '$2 ~ p && $4 == "LISTENING" {print $5}' | sort -u
    return 0
  fi
  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
    return 0
  fi
  ss -ltnp 2>/dev/null | awk -v p=":$port" '$4 ~ p {print $6}' | grep -oP 'pid=\K[0-9]+' || true
}

vc_port_busy() {
  [[ -n "$(vc_port_pids "$1")" ]]
}

vc_pick_port() {
  local port="$1"
  local force="${FORCE_PORTS:-0}"
  if [[ "$force" == "1" && -n "$(vc_port_pids "$port")" ]]; then
    vc_warn "Port $port is in use; FORCE_PORTS=1 so stopping listeners"
    # shellcheck disable=SC2046
    kill $(vc_port_pids "$port") 2>/dev/null || true
    sleep 1
  fi
  while vc_port_busy "$port"; do
    vc_warn "Port $port is in use; trying $((port + 1))"
    port=$((port + 1))
  done
  printf "%s" "$port"
}

vc_wait_http() {
  local url="$1"
  local label="$2"
  local attempts="${3:-1200}"
  local pid="${4:-}"
  local log_file="${5:-}"
  local i
  for ((i = 1; i <= attempts; i++)); do
    if [[ -n "$pid" ]] && ! kill -0 "$pid" 2>/dev/null; then
      vc_warn "$label process exited before becoming ready"
      return 1
    fi
    if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
      vc_ok "$label ready"
      return 0
    fi
    if (( i % 10 == 0 )); then
      printf "    waiting for %s (%ds)...\n" "$label" "$((i / 2))"
      if [[ -n "$log_file" && -f "$log_file" ]]; then
        tail -n 3 "$log_file" 2>/dev/null | sed 's/^/      /'
      fi
    fi
    sleep 0.5
  done
  return 1
}

vc_need_cmd() {
  command -v "$1" >/dev/null 2>&1 || vc_die "$1 is required"
}

vc_should_prefer_local() {
  # Apple Silicon: local MPS is much faster than Docker CPU on macOS
  if [[ "$(vc_detect_os)" == "darwin" && "$(vc_detect_arch)" == "arm64" ]]; then
    return 0
  fi
  # Host NVIDIA GPU: local CUDA beats Docker overhead for dev
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

vc_print_platform_summary() {
  local os arch device docker_ok docker_gpu
  os="$(vc_detect_os)"
  arch="$(vc_detect_arch)"
  device="$(vc_detect_host_device)"
  if vc_docker_running; then docker_ok="yes"; else docker_ok="no"; fi
  if vc_detect_docker_gpu; then docker_gpu="yes"; else docker_gpu="no"; fi
  vc_ok "Platform: $os ($arch) | local device: $device | docker: $docker_ok | docker GPU: $docker_gpu"
}
