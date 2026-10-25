#!/bin/zsh
# Install Sage's native app and one login LaunchAgent.
set -euo pipefail

sageProjectRoot="${SAGE_PROJECT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
sageDataRoot="${SAGE_DATA_ROOT:-/Users/hrudainirmal/SageData}"
coreEnvironmentFile="${sageDataRoot}/secrets/core.env"
currentUser="$(id -un)"
userHome="$(dscl . -read "/Users/${currentUser}" NFSHomeDirectory | awk '{print $2}')"
appPath="${userHome}/Applications/Sage.app"
appExecutable="${appPath}/Contents/MacOS/Sage"
launchAgentPath="${userHome}/Library/LaunchAgents/com.sage.desktop-app.plist"
launchAgentLabel="gui/$(id -u)/com.sage.desktop-app"

"${sageProjectRoot}/scripts/bootstrap-runtime.sh"
if [[ ! -f "${coreEnvironmentFile}" ]] \
  || ! /usr/bin/grep -q '^SAGE_OPERATOR_TOKEN=.' "${coreEnvironmentFile}" \
  || ! /usr/bin/grep -q '^SAGE_NATIVE_OBSERVER_TOKEN=.' "${coreEnvironmentFile}"; then
  print -u2 "Native Sage credentials are missing from the private Core environment"
  exit 78
fi
chmod 600 "${coreEnvironmentFile}"

if pgrep -f "^${appExecutable}$" >/dev/null; then
  pkill -TERM -f "^${appExecutable}$"
  for shutdownAttempt in {1..20}; do
    if ! pgrep -f "^${appExecutable}$" >/dev/null; then
      break
    fi
    sleep 0.25
  done
  if pgrep -f "^${appExecutable}$" >/dev/null; then
    print -u2 "Sage.app did not stop cleanly; close it before installing"
    exit 70
  fi
fi

"${sageProjectRoot}/scripts/build-macos-app.sh"

mkdir -p "${userHome}/Library/LaunchAgents" "${sageDataRoot}/logs"
sed \
  -e "s|__APP_EXECUTABLE__|${appExecutable}|g" \
  -e "s|__APP_PATH__|${appPath}|g" \
  -e "s|__LOG_ROOT__|${sageDataRoot}/logs|g" \
  "${sageProjectRoot}/launchd/com.sage.desktop-app.plist.template" \
  > "${launchAgentPath}"
chmod 600 "${launchAgentPath}"

launchctl bootout "${launchAgentLabel}" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "${launchAgentPath}"
launchctl enable "${launchAgentLabel}"
open -a "${appPath}"

print "Installed Sage.app and its login service."
