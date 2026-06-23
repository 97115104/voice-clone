#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/server"

if [[ -d "$ROOT/.venv" ]]; then
  source "$ROOT/.venv/bin/activate"
fi

PORT="${PORT:-8004}"
export PORT

echo "Starting voice clone server on http://127.0.0.1:${PORT}"
python tts_server.py
