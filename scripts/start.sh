#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib/common.sh
source "$ROOT/scripts/lib/common.sh"

cd "$ROOT/server"

py="$VC_VENV_DIR/bin/python"
[[ -x "$py" ]] || py="$VC_VENV_DIR/Scripts/python.exe"
[[ -x "$py" ]] || vc_die "Run ./install --local first"

export PORT="${PORT:-8004}"
export TTS_DEVICE="${TTS_DEVICE:-$(vc_detect_host_device)}"

vc_ok "Starting on http://127.0.0.1:$PORT (device: $TTS_DEVICE)"
exec "$py" tts_server.py
