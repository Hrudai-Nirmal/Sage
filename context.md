# Sage Context

## Purpose

Sage is a single-user, local-first personal operations assistant for macOS. Telegram is its conversational interface; Sage Core is the authoritative local state and policy service.

## Decisions

- Sage Core uses FastAPI and SQLite; n8n orchestrates deterministic external workflows.
- Sage and Iris run as separate native `mlx-vlm` launchd services; application services run through Docker Compose.
- User-authorized approvals are server-validated, single-use Telegram button actions. Models cannot approve their own work.
- Telegram ingress is restricted to the configured numeric user, one forum group, and the Main, Scheduled Reports, and Notifications topics.
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
- Tasks are approval-created and initially support title, notes, priority, due timestamp, and recurrence. New schema columns are added without dropping existing SQLite task data.
- Telegram delivery is at-least-once: Core records each Telegram message ID once and returns a successful duplicate acknowledgement for safe n8n retries.
- The versioned n8n Telegram poller runs every 30 seconds, filters incoming updates against runtime allowlists, and commits its Bot API offset only after Core accepts the batch.
- n8n permits workflow environment access only because the local poller must read its private bot and Core-ingress credentials; `configure-telegram.sh` copies only the ingress credential, never the independent approval credentials, into n8n's Telegram environment.
- Telegram task and case commands create proposals only: `/task <title>` and `/case <title> | <objective>`. Inline callbacks are allowlisted and deduplicated before the native dispatcher uses Core's isolated approval credential.
- Declining a proposal atomically closes and audits it without creating a task or case.
- launchd installation restarts already-loaded Sage services in place and persistently loads only missing user agents, preventing a partial reinstall from unloading Sage or Iris.
- The native dispatcher records credential-safe exception types in its private log and keeps retryable messages pending when a dependency is unavailable.
- Interrupted PROCESSING claims return to their queues when the dispatcher restarts; an already-applied callback becomes COMPLETE even if Telegram's short-lived acknowledgement has expired.
- Telegram mode commands are intentionally limited to `/normal`, `/eco`, `/sleep`, and `/shutdown`; restart remains available only on the Mac.
- Normal keeps Sage and Iris resident. Eco keeps the dispatcher available and loads exactly one Sage server around each ordinary message. Sleep answers only with mode guidance. Shutdown acknowledges first, then unloads all Sage launch agents, stops Docker Compose, and clears bounded temporary state.
- The n8n Telegram workflow is ingress-only. Disabled legacy model/reply nodes were removed so the native dispatcher is the only reply and model-call owner.
- Explicit `/research <question>` messages use Tavily basic search with at most three sources, then local Trafilatura extraction. Ordinary chat never infers permission to browse.
- Research provider credentials live only in `/Users/hrudainirmal/SageData/secrets/online.env`; the dispatcher receives only a separate Core research-channel credential.
- Research source text is framed as untrusted evidence for the model. Public-network URL validation, redirect validation, byte limits, source limits, durable source snapshots, retrieval timestamps, and audit events bound the online surface.
