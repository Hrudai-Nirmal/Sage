#!/bin/zsh
# Start exactly one private MLX-VLM server; launchd supervises restarts and logs.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  print -u2 "Expected exactly one model role: sage or iris"
  exit 64
fi

modelRole="$1"
sageDataRoot="${SAGE_DATA_ROOT:-/Users/hrudainirmal/SageData}"
runtimePython="${sageDataRoot}/runtime/mlx-vlm/bin/python"
secretFile="${sageDataRoot}/secrets/model-server.env"

if [[ ! -x "${runtimePython}" || ! -r "${secretFile}" ]]; then
  print -u2 "Missing MLX runtime or model server secret file"
  exit 78
fi

source "${secretFile}"

case "${modelRole}" in
  sage)
    modelPath="${sageDataRoot}/models/qwen3.5-9b-6bit"
    modelPort="${SAGE_SAGE_MODEL_PORT:-18080}"
    ;;
  iris)
    modelPath="${sageDataRoot}/models/qwen3-vl-2b-instruct-4bit"
    modelPort="${SAGE_IRIS_MODEL_PORT:-18081}"
    ;;
  *)
    print -u2 "Unsupported model role: ${modelRole}"
    exit 64
    ;;
esac

if [[ ! -d "${modelPath}" || -z "${SAGE_MODEL_API_KEY:-}" ]]; then
  print -u2 "Missing model files or SAGE_MODEL_API_KEY"
  exit 78
fi

# A reserved port may be owned only by the matching Sage model; never create a second process.
if lsof -nP -iTCP:"${modelPort}" -sTCP:LISTEN >/dev/null 2>&1; then
  discoveredModels="$(curl --connect-timeout 1 --max-time 2 --silent --show-error \
    "http://127.0.0.1:${modelPort}/v1/models" \
    -H "Authorization: Bearer ${SAGE_MODEL_API_KEY}" 2>/dev/null || true)"
  if print -r -- "${discoveredModels}" | grep -Fq "${modelPath}"; then
    exit 0
  fi

  print -u2 "Reserved model port ${modelPort} is occupied by a different process"
  exit 69
fi

# The server recognizes this environment variable; passing it on the command line leaks it to process listings.
export MLX_VLM_SERVER_API_KEY="${SAGE_MODEL_API_KEY}"
unset SAGE_MODEL_API_KEY

exec "${runtimePython}" -m mlx_vlm.server \
  --host 127.0.0.1 \
  --max-num-seqs 1 \
  --model "${modelPath}" \
  --port "${modelPort}"
