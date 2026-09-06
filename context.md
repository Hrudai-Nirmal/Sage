# Sage Context

## Purpose

Sage is a single-user, local-first personal operations assistant for macOS. Telegram is its conversational interface; Sage Core is the authoritative local state and policy service.

## Decisions

- Sage Core uses FastAPI and SQLite; n8n orchestrates deterministic external workflows.
- Sage and Iris run as separate native `mlx-vlm` launchd services; application services run through Docker Compose.
- User-authorized approvals are server-validated, single-use Telegram button actions. Models cannot approve their own work.
- Files are copied into `/Users/hrudainirmal/SageData` and never altered at their external source.
- All runtime data and secrets stay outside Git; only templates and safe configuration are versioned.

## Gotchas

- No user task, case, skill, or workflow mutation occurs without an explicit approval record.
- Docker containers must not receive broad host filesystem mounts. Sage Core owns controlled import access.
- Core uses independent proposal, approval, and operator credentials so a model-visible proposal channel cannot confirm its own actions.
- Runtime modes are `NORMAL`, `ECO`, `SLEEP`, and `SHUTDOWN`; shutdown stops Sage only and never powers off macOS.
- Model server API keys must be passed through `MLX_VLM_SERVER_API_KEY`, never as command-line arguments, because command lines are visible in process listings.
- Model ports are single-instance reservations: `18080` for Sage and `18081` for Iris. A process guard rejects an occupied port unless it belongs to the matching model.
- Daily maintenance clears only Sage temporary artifacts older than seven days and model-server memory caches; it does not delete documents, databases, model weights, or backup data.
