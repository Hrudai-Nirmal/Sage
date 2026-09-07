#!/bin/zsh
# Stop Sage-owned services and reclaim ephemeral state without deleting durable personal data.
set -euo pipefail

sageProjectRoot="${SAGE_PROJECT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
sageDataRoot="${SAGE_DATA_ROOT:-/Users/hrudainirmal/SageData}"

function stopMatchingModelServer() {
  local modelPort="$1"
  local modelPath="$2"
  local listenerPids
  listenerPids="$(lsof -t -nP -iTCP:"${modelPort}" -sTCP:LISTEN 2>/dev/null || true)"

  for listenerPid in ${(f)listenerPids}; do
    local commandLine
    commandLine="$(ps -p "${listenerPid}" -o command= 2>/dev/null || true)"
    if [[ "${commandLine}" == *"mlx_vlm.server"* && "${commandLine}" == *"${modelPath}"* ]]; then
      kill "${listenerPid}" 2>/dev/null || true
      for shutdownAttempt in {1..10}; do
        if ! kill -0 "${listenerPid}" 2>/dev/null; then
          break
        fi
        sleep 1
      done
      if kill -0 "${listenerPid}" 2>/dev/null; then
        kill -9 "${listenerPid}" 2>/dev/null || true
      fi
    fi
  done
}

for launchAgentName in com.sage.model-sage com.sage.model-iris com.sage.telegram-dispatcher; do
  launchctl unload "${HOME}/Library/LaunchAgents/${launchAgentName}.plist" 2>/dev/null || true
done
launchctl bootout "gui/${UID}/com.sage.maintenance" 2>/dev/null || true

stopMatchingModelServer "${SAGE_SAGE_MODEL_PORT:-18080}" "${sageDataRoot}/models/qwen3.5-9b-6bit"
stopMatchingModelServer "${SAGE_IRIS_MODEL_PORT:-18081}" "${sageDataRoot}/models/qwen3-vl-2b-instruct-4bit"

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  docker compose --env-file "${sageProjectRoot}/.env" --file "${sageProjectRoot}/docker-compose.yml" down --remove-orphans
fi

SAGE_DATA_ROOT="${sageDataRoot}" "${sageProjectRoot}/scripts/cleanup-runtime.sh"
