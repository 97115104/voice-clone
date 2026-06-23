#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT/.venv"
OS="$(uname -s)"

FORCE_INSTALL="${FORCE_INSTALL:-0}"
WITH_MODEL="${WITH_MODEL:-1}"

log() { printf "\n==> %s\n" "$*"; }
ok() { printf "[+] %s\n" "$*"; }
warn() { printf "[!] %s\n" "$*" >&2; }
die() { printf "[x] %s\n" "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage:
  ./install                 Install system + Python dependencies
  ./install --force         Reinstall Python packages
  ./install --skip-model    Skip Chatterbox model download

Environment:
  FORCE_INSTALL=1           Same as --force
  WITH_MODEL=0              Same as --skip-model
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --force) FORCE_INSTALL=1 ;;
      --skip-model) WITH_MODEL=0 ;;
      --help|-h) usage; exit 0 ;;
      *) die "Unknown option: $1" ;;
    esac
    shift
  done
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
  warn "ffmpeg not found (needed for MP3/Opus output)"
  if [[ "$OS" == "Darwin" ]] && command -v brew >/dev/null 2>&1; then
    log "Installing ffmpeg via Homebrew"
    brew install ffmpeg
    ok "ffmpeg installed"
    return 0
  fi
  if [[ "$OS" == "Linux" ]] && command -v apt-get >/dev/null 2>&1; then
    log "Installing ffmpeg via apt"
    sudo apt-get update -qq
    sudo apt-get install -y ffmpeg
    ok "ffmpeg installed"
    return 0
  fi
  warn "Install ffmpeg manually, then rerun ./install"
}

ensure_venv() {
  local py
  py="$(find_python)" || die "Python 3.10+ is required"
  ok "Using $py ($("$py" --version))"

  if [[ ! -d "$VENV_DIR" ]]; then
    log "Creating virtualenv at .venv"
    "$py" -m venv "$VENV_DIR"
  fi

  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  python -m pip install --upgrade pip wheel "setuptools<82" >/dev/null
}

install_torch() {
  log "Installing PyTorch"
  if [[ "$OS" == "Darwin" ]]; then
    pip install torch torchaudio
    return 0
  fi
  if command -v nvidia-smi >/dev/null 2>&1; then
    ok "NVIDIA GPU detected"
    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
    return 0
  fi
  warn "No NVIDIA GPU detected; installing CPU build of PyTorch"
  pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
}

ensure_setuptools_compat() {
  # resemble-perth imports pkg_resources; setuptools 82+ removed it
  ensure_venv
  pip install "setuptools<82" >/dev/null
}

install_python_deps() {
  ensure_setuptools_compat
  install_torch
  log "Installing Python dependencies"
  pip install -r "$ROOT/requirements.txt"
  ok "Python packages installed"
}

deps_ready() {
  [[ -x "$VENV_DIR/bin/python" ]] || return 1
  "$VENV_DIR/bin/python" -c "
import torch, chatterbox, fastapi, uvicorn, soundfile
import perth
assert perth.PerthImplicitWatermarker is not None, 'resemble-perth broken (check setuptools<82)'
" >/dev/null 2>&1
}

download_model() {
  local marker="$VENV_DIR/.model-ready"
  if [[ "$FORCE_INSTALL" != "1" && -f "$marker" ]]; then
    ok "Chatterbox model already downloaded"
    return 0
  fi

  log "Downloading Chatterbox model weights (first install only — may take several minutes)"
  "$VENV_DIR/bin/python" - <<'PY'
import os
import time
import torch
from chatterbox.tts import ChatterboxTTS

device = os.environ.get("TTS_DEVICE") or ("cuda" if torch.cuda.is_available() else "cpu")
print(f"[install] loading model on {device}", flush=True)
t0 = time.time()
ChatterboxTTS.from_pretrained(device=device)
print(f"[install] model ready in {time.time() - t0:.1f}s", flush=True)
PY
  touch "$marker"
  ok "Chatterbox model downloaded"
}

install_all() {
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
    ok "Skipped model download (weights will download on first server start)"
  fi

  echo ""
  ok "Install complete"
  echo ""
  echo "  Activate:  source .venv/bin/activate"
  echo "  Start:     ./scripts/deploy-locally.sh"
  echo "             ./scripts/start.sh"
  echo ""
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  parse_args "$@"
  install_all
fi
