#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=lib/common.sh
source "$ROOT/scripts/lib/common.sh"
# shellcheck source=install-deps.sh
source "$ROOT/scripts/install-deps.sh"

vc_log "Running platform checks"
vc_print_platform_summary

vc_need_cmd bash
vc_ok "bash OK"

if vc_resolve_docker >/dev/null 2>&1; then
  if vc_docker_running; then
    vc_ok "docker daemon running"
    if vc_docker_compose_cmd >/dev/null; then
      vc_ok "docker compose: $(vc_docker_compose_cmd)"
    else
      vc_warn "docker compose not found"
    fi
  else
    vc_warn "docker installed but not running"
  fi
else
  vc_warn "docker not found"
fi

device="$(vc_detect_host_device)"
vc_ok "detected local device: $device"

if [[ -x "$VC_VENV_DIR/bin/python" ]] || [[ -x "$VC_VENV_DIR/Scripts/python.exe" ]]; then
  if deps_ready 2>/dev/null; then
    vc_ok "local venv dependencies OK"
  else
    vc_warn "local venv incomplete — run ./install --local"
  fi
else
  vc_warn "no local venv — run ./install --local or use Docker"
fi

for f in "$ROOT/scripts/lib/common.sh" "$ROOT/scripts/install-deps.sh" \
         "$ROOT/scripts/deploy.sh" "$ROOT/scripts/deploy-docker.sh" \
         "$ROOT/scripts/deploy-locally.sh" "$ROOT/scripts/start.sh"; do
  bash -n "$f"
  vc_ok "syntax: ${f#$ROOT/}"
done

python3 -m py_compile "$ROOT/server/tts_server.py"
vc_ok "tts_server.py syntax OK"

# Empty-array expansion must not trip set -u (macOS bash)
DEPLOY_EXTRA=()
if ((${#DEPLOY_EXTRA[@]} > 0)); then :; fi
vc_ok "empty array guard OK"

vc_ok "All checks passed"
