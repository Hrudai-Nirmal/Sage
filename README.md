# Sage

Sage is a single-user, local-first personal operations assistant for macOS. Telegram will be its conversation interface; the local operator interface covers system controls, state, approvals, documents, audits, and backups.

## Current foundation

- Native MLX-VLM model services are verified with Sage (`Qwen3.5-9B-6bit`) and Iris (`Qwen3-VL-2B-Instruct-4bit`).
- Sage Core is a FastAPI + SQLite service with durable modes, task/case approval gates, separate proposal/approval/operator credentials, and an audit trail.
- Docker Compose defines local-only Sage Core and n8n services. Native launchd templates own model services.
- The managed data root is `/Users/hrudainirmal/SageData`; all runtime state and secrets are excluded from Git.

The Telegram bot, Google OAuth, n8n workflows, external-folder import allowlist, document registry, skills, and backup scheduler remain to be implemented after their required credentials and configuration are available.

## Local setup

The runtime bootstrap has already been run for this machine. It is safe to rerun and never overwrites existing credentials:

```zsh
SAGE_DATA_ROOT=/Users/hrudainirmal/SageData scripts/bootstrap-runtime.sh
```

It creates the managed structure, including `context`, `skills`, `tools`, `documents`, `archives`, `research`, `temp`, `backups`, `logs`, and private service credentials. Source folders such as Downloads are intentionally not configured yet.

Start Docker Desktop, then validate and launch the app services:

```zsh
docker compose config
docker compose up --build -d
```

Core listens only on `127.0.0.1:8787`, and n8n listens only on `127.0.0.1:5678`.

Install native model services after Docker is available and the machine is intended to run in normal mode:

```zsh
scripts/install-launchd.sh
```

This registers separate user launch agents for Sage on port `18080` and Iris on port `18081`. Both bind only to loopback and require the private model-server token.

## Verification

```zsh
/Users/hrudainirmal/SageData/runtime/sage-core/bin/python -m pytest -q
```

## Security boundaries

- Sage never writes to external source folders; future imports copy into the managed data root.
- Task, case, skill, and workflow changes are designed to use one-time user approvals. Core distinguishes the agent proposal channel from the approval channel.
- Secrets have mode `0600` under `/Users/hrudainirmal/SageData/secrets` and are not tracked by Git.
- Model services and Docker application ports are loopback-only.
