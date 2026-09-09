#!/bin/zsh
# Apply one user-approved Sage operating mode without affecting macOS itself.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  print -u2 "Expected exactly one mode: normal, eco, sleep, or shutdown"
  exit 64
fi

requestedMode="${1:u}"
if [[ "${requestedMode}" != "NORMAL" && "${requestedMode}" != "ECO" && "${requestedMode}" != "SLEEP" && "${requestedMode}" != "SHUTDOWN" ]]; then
  print -u2 "Unsupported Sage mode: $1"
  exit 64
fi

sageProjectRoot="${SAGE_PROJECT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
sageDataRoot="${SAGE_DATA_ROOT:-/Users/hrudainirmal/SageData}"
source "${sageDataRoot}/secrets/core.env"

curl --fail --silent --show-error --request PATCH \
  --header "X-Sage-Operator-Token: ${SAGE_OPERATOR_TOKEN}" \
  --header "Content-Type: application/json" \
  --data "{\"mode\":\"${requestedMode}\"}" \
  http://127.0.0.1:8787/v1/system/mode >/dev/null

function loadLaunchAgent() {
  local agentName="$1"
  local agentPath="${HOME}/Library/LaunchAgents/${agentName}.plist"
  if launchctl list | rg -q "${agentName}"; then
    launchctl kickstart -k "gui/${UID}/${agentName}"
  else
    launchctl load -w "${agentPath}"
  fi
}

function unloadModelAgent() {
  local agentName="$1"
  launchctl unload "${HOME}/Library/LaunchAgents/${agentName}.plist" 2>/dev/null || true
}

case "${requestedMode}" in
  NORMAL)
    loadLaunchAgent com.sage.telegram-dispatcher
    loadLaunchAgent com.sage.maintenance
    loadLaunchAgent com.sage.model-sage
    loadLaunchAgent com.sage.model-iris
    ;;
  ECO|SLEEP)
    # Telegram remains the remote wake/control plane while model memory is released.
    loadLaunchAgent com.sage.telegram-dispatcher
    loadLaunchAgent com.sage.maintenance
    unloadModelAgent com.sage.model-sage
    unloadModelAgent com.sage.model-iris
    ;;
  SHUTDOWN)
    SAGE_DATA_ROOT="${sageDataRoot}" SAGE_PROJECT_ROOT="${sageProjectRoot}" \
      "${sageProjectRoot}/scripts/shutdown-sage.sh"
    ;;
esac
