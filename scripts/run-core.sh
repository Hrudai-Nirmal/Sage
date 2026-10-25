#!/bin/zsh
# Run LifeOps Core natively so every SQLite writer shares macOS filesystem locking.
set -euo pipefail

sageDataRoot="${SAGE_DATA_ROOT:-/Users/hrudainirmal/SageData}"
sageProjectRoot="${SAGE_PROJECT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
coreRuntime="${sageDataRoot}/runtime/sage-core"

export SAGE_DATA_ROOT="${sageDataRoot}"
export SAGE_DOWNLOADS_IMPORT_ROOT="/Users/hrudainirmal/Downloads"
export PYTHONPATH="${sageProjectRoot}/src"

if [[ ! -x "${coreRuntime}/bin/uvicorn" ]]; then
  print -u2 "Sage Core runtime is unavailable"
  exit 78
fi

exec "${coreRuntime}/bin/python" -m sage_core.runtime_environment \
  "${sageDataRoot}/secrets/core.env" \
  "${sageDataRoot}/secrets/telegram.env" \
  "${sageDataRoot}/secrets/online.env" \
  "${sageDataRoot}/secrets/google.env"
