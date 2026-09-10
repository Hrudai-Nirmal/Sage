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
- General Tavily searches boost Indian results because Sage's configured user locale is New Delhi; the original query remains unchanged in the durable research record.
- Deterministic natural-language phrases such as “look for”, “search online for”, and “look up” invoke research without requiring a slash command. A direct “try it” follow-up reuses the preceding explicit search request, and ordinary model replies receive four recent completed Telegram turns.
- Lifecycle integration tests replace `launchctl`, `lsof`, and Docker with isolated fakes; tests must never unload or stop the live Mac services.
- Model role contracts are versioned in `prompts/sage-system.md` and `prompts/iris-system.md`. The dispatcher applies each contract to its matching request because OpenAI-compatible system prompts are request-scoped.
- Research replies append provider-returned URLs outside model generation. Direct source follow-ups read the latest durable research record and do not spend another search credit.
- Telegram conversation ingress is Main-only; Scheduled Reports and Notifications are output topics. Approval callbacks remain accepted from all configured topics.
- Iris accepts Telegram JPEG, PNG, WebP, and PDF attachments through request-scoped multimodal prompts. Downloads are capped at 20 MB, PDFs render only their first page, and every temporary artifact is removed in a `finally` boundary.
- The localhost operator dashboard at `/operator` is an observation and runtime-control surface, not a second chat. It shows bounded recent approvals, tasks, cases, documents, research, schedules, and audit events.
- Dashboard mode requests are persisted by Core and reconciled once by the native dispatcher. Normal keeps the two exact model agents resident; Eco and Sleep unload them; Shutdown starts the established clean shutdown path.
- Scheduled reports and notifications require the same Telegram button approval as tasks and cases. SQLite materializes missed runs into a single durable delivery queue, restores interrupted claims, advances recurrence from the original due time, and retries transient delivery failures with bounded exponential backoff.
- Scheduled reports receive a bounded snapshot of current open tasks and active cases. Notifications are deterministic text and do not invoke a model.
- Google OAuth credentials remain encrypted inside n8n. A separate private `google.env` maps stable account keys to exact mailbox identities and shares only an ingress token with Core and n8n.
- The Google poller checks every five minutes and indexes only resources arriving or changing after its activation boundary. Core validates each claimed account identity and deduplicates Gmail messages by account and Gmail message ID.
- Gmail polling uses read-only list/get requests and never marks mail read. `/mail [terms]` searches bounded local snapshots across personal-work, work, personal, and college.
- Calendar polling is restricted to the personal-work account and indexes events updated after activation. `/calendar [terms]` searches the local snapshot; the poller does not create, update, or delete events.
- Drive metadata polling covers all four accounts and indexes files modified after activation without downloading their content. `/drive [terms]` returns locally indexed metadata and Google-provided view links; upload, content update, and deletion are absent from this workflow.
