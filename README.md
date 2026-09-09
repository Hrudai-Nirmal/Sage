# Sage

Sage is a single-user, local-first personal operations assistant for macOS. Telegram will be its conversation interface; the local operator interface covers system controls, state, approvals, documents, audits, and backups.

## Current foundation

- Native MLX-VLM model services are verified with Sage (`Qwen3.5-9B-6bit`) and Iris (`Qwen3-VL-2B-Instruct-4bit`).
- Sage Core is a FastAPI + SQLite service with durable modes, task/case approval gates, separate proposal/approval/operator credentials, an audit trail, and an allowlisted Telegram ingress boundary.
- Online research uses Tavily basic search plus local Trafilatura extraction, with bounded source counts, public-network URL checks, durable citations, and retrieval audit events.
- Versioned role contracts in `prompts/` define Sage's user-facing authority and Iris's restricted background-analysis role. The dispatcher loads Sage's prompt for every model call.
- Docker Compose defines local-only Sage Core and n8n services. Native launchd templates own model services.
- The managed data root is `/Users/hrudainirmal/SageData`; all runtime state and secrets are excluded from Git.

Telegram routing is configured privately for the chosen forum group. The active n8n poller is ingress-only; one native dispatcher owns all replies and model calls. Google OAuth, skills, and backup scheduling remain to be implemented after their required credentials and configuration are available.

## Local setup

The runtime bootstrap has already been run for this machine. It is safe to rerun and never overwrites existing credentials:

```zsh
SAGE_DATA_ROOT=/Users/hrudainirmal/SageData scripts/bootstrap-runtime.sh
```

It creates the managed structure, including `context`, `skills`, `tools`, `documents`, `archives`, `research`, `temp`, `backups`, `logs`, and private service credentials. Downloads is the sole configured external source and imports are copy-only.

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

The same installer registers a daily 03:15 IST maintenance agent. It removes only temporary files older than seven days and resets the in-memory cache of either active model server. To stop Sage cleanly without deleting its personal state:

```zsh
scripts/shutdown-sage.sh
```

Runtime modes can be changed locally with `scripts/set-sage-mode.sh <mode>` or from the Main Telegram topic:

- `/normal` keeps Sage and Iris loaded.
- `/eco` unloads both models between requests and temporarily loads only Sage on demand.
- `/sleep` keeps Telegram mode control available but does not run model work.
- `/shutdown` confirms in Telegram, then stops Sage launch agents, containers, and temporary state. Restart remains local-only.

Use `/research <question>` in the Main Telegram topic for current online research. Explicit natural phrasing such as “look for”, “search online for”, or “look up” works too. Sage retrieves at most three India-boosted sources, extracts readable page content locally, treats all retrieved text as untrusted, and returns a timestamped answer with numbered citations. Ambiguous ordinary conversation does not silently trigger web access.

## Verification

```zsh
/Users/hrudainirmal/SageData/runtime/sage-core/bin/python -m pytest -q
```

## Security boundaries

- Sage never writes to external source folders; future imports copy into the managed data root.
- Task, case, skill, and workflow changes are designed to use one-time user approvals. Core distinguishes the agent proposal channel from the approval channel.
- Telegram messages are accepted only from the configured numeric user and Sage forum topics; retrying the same Telegram message ID is safe.
- n8n only ingests allowlisted Telegram updates. The single native dispatcher is the sole owner of Telegram replies and Sage model calls.
- `/task <title>` and `/case <title> | <objective>` return Telegram approval cards. Only the configured user's one-time Approve or Decline callback can resolve the proposal.
- Secrets have mode `0600` under `/Users/hrudainirmal/SageData/secrets` and are not tracked by Git.
- Model services and Docker application ports are loopback-only.
- A model server never starts when its reserved port belongs to another process; a matching existing server is reused instead of duplicated.
- Online fetches accept only HTTP(S), reject credentials in URLs and non-public resolved addresses, validate redirects, cap pages at 2 MB, and retain at most 30,000 extracted characters per source.
