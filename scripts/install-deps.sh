#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/common.sh
source "$ROOT/scripts/lib/common.sh"

ROOT="$VC_ROOT"
VENV_DIR="$VC_VENV_DIR"
OS="$(vc_detect_os)"

FORCE_INSTALL="${FORCE_INSTALL:-0}"
WITH_MODEL="${WITH_MODEL:-1}"
MODE="${MODE:-auto}"

log() { vc_log "$@"; }
ok() { vc_ok "$@"; }
warn() { vc_warn "$@"; }
die() { vc_die "$@"; }

usage() {
  cat <<'EOF'
Usage:
  ./install                 Auto: Docker image if Docker available, else local Python
  ./install --local         Force local Python virtualenv install
  ./install --docker        Force Docker image build only
  ./install --force         Reinstall / rebuild
  ./install --skip-model    Skip Chatterbox model download (local mode)

Environment:
  MODE=local|docker|auto    Install mode (default: auto)
  FORCE_INSTALL=1           Same as --force
  WITH_MODEL=0              Same as --skip-model
  TTS_DEVICE=cuda|mps|cpu   Override device for local install
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --force) FORCE_INSTALL=1 ;;
      --skip-model) WITH_MODEL=0 ;;
      --local) MODE="local" ;;
      --docker) MODE="docker" ;;
      --help|-h) usage; exit 0 ;;
      *) die "Unknown option: $1" ;;
    esac
    shift
  done
}

resolve_mode() {
  if [[ "$MODE" != "auto" ]]; then
    ok "Install mode: $MODE"
    vc_print_platform_summary
    return 0
  fi

  if vc_should_prefer_local && find_python >/dev/null 2>&1; then
    MODE="local"
    ok "Install mode: local (GPU/MPS available on host)"
  elif vc_docker_running; then
    MODE="docker"
    ok "Install mode: docker"
  elif vc_resolve_docker >/dev/null 2>&1; then
    warn "Docker is installed but not running — using local Python install"
    warn "Start Docker Desktop and rerun ./install --docker"
    MODE="local"
  else
    MODE="local"
    ok "Install mode: local"
  fi
  vc_print_platform_summary
}

find_python() {
  local candidates=(python3.12 python3.11 python3.10 python3)
  local py
  for py in "${candidates[@]}"; do
    if command -v "$py" >/dev/null 2>&1; then
      local major minor
      major="$("$py" -c 'import sys; print(sys.version_info.major)')"
      minor="$("$py" -c 'import sys; print(sys.version_info.minor)')"
      if (( major == 3 && minor >= 10 )); then
        printf "%s" "$py"
        return 0
      fi
    fi
  done
  return 1
}

ensure_ffmpeg() {
  if command -v ffmpeg >/dev/null 2>&1; then
    ok "ffmpeg found"
    return 0
  fi
  warn "ffmpeg not found (needed for MP3/Opus and mic recordings)"
  if [[ "$OS" == "darwin" ]] && command -v brew >/dev/null 2>&1; then
    log "Installing ffmpeg via Homebrew"
    brew install ffmpeg
    ok "ffmpeg installed"
    return 0
  fi
  if [[ "$OS" == "linux" ]] && command -v apt-get >/dev/null 2>&1; then
    log "Installing ffmpeg via apt"
    sudo apt-get update -qq
    sudo apt-get install -y ffmpeg
    ok "ffmpeg installed"
    return 0
  fi
  if [[ "$OS" == "windows" ]] && command -v winget >/dev/null 2>&1; then
    warn "Install ffmpeg: winget install Gyan.FFmpeg"
    return 0
  fi
  warn "Install ffmpeg manually, then rerun ./install --local"
}

ensure_venv() {
  local py
  py="$(find_python)" || die "Python 3.10+ is required for local install"
  ok "Using $py ($("$py" --version))"

  if [[ ! -d "$VENV_DIR" ]]; then
    log "Creating virtualenv at .venv"
    "$py" -m venv "$VENV_DIR"
  fi

  # shellcheck disable=SC1091
  if [[ -f "$VENV_DIR/bin/activate" ]]; then
    source "$VENV_DIR/bin/activate"
  elif [[ -f "$VENV_DIR/Scripts/activate" ]]; then
    source "$VENV_DIR/Scripts/activate"
  else
    die "Could not find venv activate script"
  fi
  python -m pip install --upgrade pip wheel "setuptools<82" >/dev/null
}

ensure_setuptools_compat() {
  ensure_venv
  pip install "setuptools<82" >/dev/null
}

install_torch() {
  local device torch_index
  device="$(vc_detect_host_device)"
  log "Installing PyTorch for device: $device"

  if [[ "$device" == "cuda" ]]; then
    torch_index="$(vc_torch_index_for_device cuda)"
    pip install torch torchaudio --index-url "$torch_index"
    return 0
  fi

  if [[ "$device" == "mps" ]]; then
    pip install torch torchaudio
    return 0
  fi

  warn "No NVIDIA GPU detected; installing CPU build of PyTorch"
  pip install torch torchaudio --index-url "$(vc_torch_index_for_device cpu)"
}

install_python_deps() {
  ensure_setuptools_compat
  install_torch
  log "Installing Python dependencies"
  pip install -r "$ROOT/requirements.txt"
  ok "Python packages installed"
}

deps_ready() {
  local py="$VENV_DIR/bin/python"
  [[ -x "$py" ]] || py="$VENV_DIR/Scripts/python.exe"
  [[ -x "$py" ]] || return 1
  "$py" -c "
import torch, chatterbox, fastapi, uvicorn, soundfile
import perth
assert perth.PerthImplicitWatermarker is not None, 'resemble-perth broken (check setuptools<82)'
" >/dev/null 2>&1
}

download_model() {
  local marker="$VENV_DIR/.model-ready"
  local py="$VENV_DIR/bin/python"
  [[ -x "$py" ]] || py="$VENV_DIR/Scripts/python.exe"

  if [[ "$FORCE_INSTALL" != "1" && -f "$marker" ]]; then
    ok "Chatterbox model already downloaded"
    return 0
  fi

  local device
  device="$(vc_detect_host_device)"
  export TTS_DEVICE="$device"

  log "Downloading Chatterbox model on $device (first install — may take several minutes)"
  "$py" - <<'PY'
import os
import time
import torch
from chatterbox.tts import ChatterboxTTS

def pick_device():
    d = os.environ.get("TTS_DEVICE")
    if d:
        return d
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"

device = pick_device()
print(f"[install] loading model on {device}", flush=True)
t0 = time.time()
ChatterboxTTS.from_pretrained(device=device)
print(f"[install] model ready in {time.time() - t0:.1f}s", flush=True)
PY
  touch "$marker"
  ok "Chatterbox model downloaded"
}

install_docker() {
  local compose_cmd gpu=0
  compose_cmd="$(vc_docker_compose_cmd)" || die "docker compose is required for --docker install"
  vc_docker_running || die "Docker is not running. Start Docker Desktop / dockerd and retry."

  if vc_detect_docker_gpu; then
    gpu=1
    ok "NVIDIA GPU detected — building CUDA image"
  else
    ok "No Docker GPU — building CPU image (normal on macOS)"
  fi

  log "Building Docker image"
  if [[ "$gpu" == "1" ]]; then
    $compose_cmd -f "$ROOT/docker-compose.yml" -f "$ROOT/docker-compose.gpu.yml" build
  else
    $compose_cmd -f "$ROOT/docker-compose.yml" build
  fi
  ok "Docker image ready"
}

install_local() {
  ensure_ffmpeg
  ensure_setuptools_compat

  if [[ "$FORCE_INSTALL" == "1" ]] || ! deps_ready; then
    install_python_deps
  else
    ok "Python dependencies already installed (use --force to reinstall)"
    ensure_venv
  fi

  if [[ "$FORCE_INSTALL" == "1" ]]; then
    rm -f "$VENV_DIR/.model-ready"
  fi

  if [[ "$WITH_MODEL" == "1" ]]; then
    download_model
  else
    ok "Skipped model download (weights download on first server start)"
  fi
}

install_all() {
  resolve_mode
  case "$MODE" in
    docker) install_docker ;;
    local)  install_local ;;
    *) die "Unknown mode: $MODE" ;;
  esac

  echo ""
  ok "Install complete"
  echo ""
  if [[ "$MODE" == "docker" ]]; then
    echo "  Start:  ./scripts/deploy.sh"
    echo "          ./scripts/deploy-docker.sh"
  else
    echo "  Start:  ./scripts/deploy.sh --local"
    echo "          ./scripts/deploy-locally.sh"
  fi
  echo ""
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  parse_args "$@"
  install_all
fi
