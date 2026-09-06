#!/bin/zsh
# Reclaim bounded Sage temporary state without touching imported documents or model weights.
set -euo pipefail

sageDataRoot="${SAGE_DATA_ROOT:-/Users/hrudainirmal/SageData}"
tempRoot="${sageDataRoot}/temp"
secretFile="${sageDataRoot}/secrets/model-server.env"

if [[ "${sageDataRoot}" == "/" || ! -d "${tempRoot}" || ! -r "${secretFile}" ]]; then
  print -u2 "Sage data root, temporary directory, or model secret file is unavailable"
  exit 78
fi

# Temporary work has no durable value after one week. Managed documents, archives, and model caches are excluded.
find "${tempRoot}" -depth -type f -mtime +7 -delete
find "${tempRoot}" -depth -type d -empty -mtime +7 -delete

source "${secretFile}"
for modelPort in "${SAGE_SAGE_MODEL_PORT:-18080}" "${SAGE_IRIS_MODEL_PORT:-18081}"; do
  if lsof -nP -iTCP:"${modelPort}" -sTCP:LISTEN >/dev/null 2>&1; then
    curl --connect-timeout 1 --max-time 2 --silent --show-error \
      --output /dev/null \
      --request POST "http://127.0.0.1:${modelPort}/v1/cache/reset" \
      -H "Authorization: Bearer ${SAGE_MODEL_API_KEY}" || true
  fi
done
