#!/bin/zsh
# Install user-scoped model launch agents after runtime secrets and models exist.
set -euo pipefail

sageProjectRoot="$(cd "$(dirname "$0")/.." && pwd)"
sageDataRoot="${SAGE_DATA_ROOT:-/Users/hrudainirmal/SageData}"
launchAgentRoot="${HOME}/Library/LaunchAgents"

if [[ ! -d "${sageDataRoot}/models/qwen3.5-9b-6bit" || ! -d "${sageDataRoot}/models/qwen3-vl-2b-instruct-4bit" ]]; then
  print -u2 "Required Sage and Iris model directories are missing"
  exit 78
fi

mkdir -p "${launchAgentRoot}" "${sageDataRoot}/logs"

for agentName in com.sage.model-sage com.sage.model-iris com.sage.maintenance; do
  templatePath="${sageProjectRoot}/launchd/${agentName}.plist.template"
  destinationPath="${launchAgentRoot}/${agentName}.plist"
  renderedTemplate="$(sed -e "s|__SAGE_PROJECT_ROOT__|${sageProjectRoot}|g" -e "s|__SAGE_DATA_ROOT__|${sageDataRoot}|g" "${templatePath}")"
  print -r -- "${renderedTemplate}" > "${destinationPath}"
  plutil -lint "${destinationPath}"
  launchctl bootout "gui/${UID}/${agentName}" 2>/dev/null || true
  launchctl bootstrap "gui/${UID}" "${destinationPath}"
done
