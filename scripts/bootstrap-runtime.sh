#!/bin/zsh
# Create private Sage runtime state once, keeping generated credentials out of Git.
set -euo pipefail

sageProjectRoot="${SAGE_PROJECT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
sageDataRoot="${SAGE_DATA_ROOT:-/Users/hrudainirmal/SageData}"
secretRoot="${sageDataRoot}/secrets"

if [[ "${sageDataRoot}" == "/" ]]; then
  print -u2 "SAGE_DATA_ROOT must not be the filesystem root"
  exit 64
fi

for relativeDirectory in \
  "archives" \
  "backups" \
  "context" \
  "database" \
  "documents/general" \
  "documents/identity" \
  "documents/owned-items" \
  "documents/personal" \
  "imports" \
  "logs" \
  "research" \
  "secrets" \
  "skills/approved" \
  "skills/pending" \
  "temp" \
  "tools"; do
  mkdir -p "${sageDataRoot}/${relativeDirectory}"
done

umask 077

if [[ ! -f "${secretRoot}/core.env" ]]; then
  {
    print "SAGE_APPROVAL_TOKEN=$(openssl rand -hex 32)"
    print "SAGE_OPERATOR_TOKEN=$(openssl rand -hex 32)"
    print "SAGE_PROPOSAL_TOKEN=$(openssl rand -hex 32)"
  } > "${secretRoot}/core.env"
fi

if [[ ! -f "${secretRoot}/model-server.env" ]]; then
  print "SAGE_MODEL_API_KEY=$(openssl rand -hex 32)" > "${secretRoot}/model-server.env"
fi

if [[ ! -f "${secretRoot}/n8n.env" ]]; then
  {
    print "N8N_ENCRYPTION_KEY=$(openssl rand -hex 32)"
    print "N8N_USER_FOLDER=/home/node/.n8n"
  } > "${secretRoot}/n8n.env"
fi

chmod 600 "${secretRoot}"/*.env

if [[ ! -f "${sageProjectRoot}/.env" ]]; then
  {
    print "SAGE_DATA_ROOT=${sageDataRoot}"
    print "SAGE_CORE_ENV_FILE=${secretRoot}/core.env"
    print "SAGE_N8N_ENV_FILE=${secretRoot}/n8n.env"
    print "SAGE_DOWNLOADS_HOST_PATH=/Users/hrudainirmal/Downloads"
    print "TZ=Asia/Kolkata"
  } > "${sageProjectRoot}/.env"
  chmod 600 "${sageProjectRoot}/.env"
fi

if ! grep -q '^SAGE_DOWNLOADS_HOST_PATH=' "${sageProjectRoot}/.env"; then
  print "SAGE_DOWNLOADS_HOST_PATH=/Users/hrudainirmal/Downloads" >> "${sageProjectRoot}/.env"
fi
