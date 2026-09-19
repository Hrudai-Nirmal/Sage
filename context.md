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
- The versioned n8n Telegram poller runs every five seconds, filters incoming updates against runtime allowlists, and commits its Bot API offset only after Core accepts the batch. The previous 30-second cadence caused roughly 15 seconds of average ingress latency before model work began.
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
- Gmail composition uses immutable rows in `email_drafts`: each edit appends a version, supersedes an older pending approval, and requires a new approval card bound to the exact current snapshot. Draft and revision calls carry Telegram-derived idempotency keys so dispatcher recovery cannot duplicate versions. Draft status mirrors the approved outbox through `PENDING_APPROVAL`, `APPROVED`, `SENDING`, `FAILED`, `SENT`, `QUARANTINED`, or user cancellation; the operator surface shows bounded metadata without exposing message bodies.
- Research replies append provider-returned URLs outside model generation. Direct source follow-ups read the latest durable research record and do not spend another search credit.
- Telegram conversation ingress is Main-only; Scheduled Reports and Notifications are output topics. Approval callbacks remain accepted from all configured topics.
- Iris accepts Telegram JPEG, PNG, WebP, and PDF attachments through request-scoped multimodal prompts. Downloads are capped at 20 MB, PDFs render only their first page, and every temporary artifact is removed in a `finally` boundary.
- The localhost operator dashboard at `/operator` is an observation and runtime-control surface, not a second chat. It shows bounded recent approvals, tasks, cases, documents, research, schedules, and audit events.
- Dashboard mode requests are persisted by Core and reconciled once by the native dispatcher. Normal keeps the two exact model agents resident; Eco and Sleep unload them; Shutdown starts the established clean shutdown path.
- Scheduled reports and notifications require the same Telegram button approval as tasks and cases. SQLite materializes missed runs into a single durable delivery queue, restores interrupted claims, advances recurrence from the original due time, and retries transient delivery failures with bounded exponential backoff.
- Scheduled reports receive a bounded snapshot of current open tasks and active cases. Notifications are deterministic text and do not invoke a model.
- Google OAuth credentials remain encrypted inside n8n. A separate private `google.env` maps stable account keys to exact mailbox identities and shares only an ingress token with Core and n8n.
- Gmail polling checks every five minutes. Core validates each claimed account identity, deduplicates messages by account and Gmail message ID, and queues each new message once for conservative local triage.
- Gmail polling uses read-only list/get requests and never marks mail read. `/mail [terms]` and explicit read wording such as “check my mail,” “do I have emails from …,” or “check recent notifications from …” search bounded local snapshots across personal-work, work, personal, and college instead of falling through to the model. Multiple named senders use OR semantics and sender-only matching to avoid unrelated body-text hits.
- Deterministic Gmail intent routing accepts both mailbox-first wording (`search my mail for assessment links`) and content-first wording (`look for assessment links in my mails`). Keeping both forms outside model discretion prevents a local model response from falsely denying configured Gmail access.
- The centralized capability broker is the authority for Sage's complete ability catalog, approval class, and retry safety. A generated manifest is appended to every Sage system prompt, so capability awareness does not depend on model memory. One explicitly named read source may be inferred automatically; multiple named sources produce a clarification instead of an arbitrary choice.
- Retry-safe capabilities receive at most three technical attempts: immediately, then after one and two seconds. Empty results are successful reads; validation, permission, and policy failures never retry. Direct non-idempotent Drive writes execute once. Exhausted retries are reported only in the current chat as temporary unavailability, never as a missing capability.
- Model replies that deny a configured capability are rejected. When a successful tool receipt exists, the dispatcher replaces the denial with deterministic grounded results; without a receipt, it truthfully states that the integration is configured but unverified for that turn.
- Calendar polling is restricted to the personal-work account and runs every 30 minutes. Confirmed timed events create durable deterministic reminders due 10 minutes before their start; changed and cancelled events replace or remove pending reminders. `/calendar [terms]` searches the local snapshot.
- The existing Telegram dispatcher owns Calendar reminder and email-triage jobs, so these features do not create additional Sage or Iris processes. Sleep and Shutdown retain due work as backlog; Normal and Eco deliver it.
- Email triage automatically notifies only for explicit security, billing, placement, or deadline signals. Gmail is never marked read. Explicit deadline/action language may create a task proposal, but only the user's Telegram approval can materialize it.
- Drive is never polled. `/drive [terms]` queries all four accounts live through credential-bound local n8n webhooks. `/drive-folder <account> | <name> | [parent-id]` and `/drive-rename <account> | <file-id> | <new-name>` are explicit on-demand writes. `/drive-delete <account> | <file-id> | <name>` always creates an independently approved durable deletion job.
- The Drive webhook token is distinct from Google ingress and is shared only with n8n and the host dispatcher. Google OAuth tokens remain encrypted in n8n.
- Ordinary Telegram chat now uses a closed model-visible capability registry for Gmail, Calendar, and Drive. Qwen chooses from JSON-schema tools, but deterministic code validates all arguments, rejects unavailable capabilities and implicit Drive mutations, limits each turn to three calls and one mutation, bounds evidence returned to the model, and keeps deletion behind the isolated approval channel. Exact commands and recognized Gmail phrasing remain fast deterministic shortcuts.
- Gmail send and Calendar delete proposals are independently approved and deduplicated by Telegram message. Approved sends enter a durable `google_actions` outbox at `CREATE_DRAFT`; the worker persists the Gmail draft ID before a separate `SEND_DRAFT` attempt. Explicit personal-work Calendar creates and updates enter the same outbox directly, while deletes enter only after approval. Calendar create retries use a deterministic Google event ID.
- A complete Gmail draft followed by an affirmative response or an explicit request for approval buttons is forced into the Gmail proposal tool. Chat confirmation never authorizes delivery: it only creates the independently authenticated, one-time Telegram Approve/Decline card.
- Gmail approval-card requests use eight recent turns and accept ordinary affirmative wording, action phrases, and requests to show the buttons again. Negation, hesitation, cancellation, or correction language always wins and prevents a proposal; Sage must never demand a magic sentence.
- Explicit recipient addresses in a send request must exactly match the model-proposed recipient set before an approval card can be created. Known-invalid pending Google actions can be quarantined with audit evidence, keeping them durable but permanently ineligible for worker delivery.
- The credential-bound `Sage Google Action Tool` n8n workflow has no schedule trigger. Four Gmail endpoints and one personal-work Calendar endpoint require a private action token, while OAuth credentials remain encrypted in n8n. The existing dispatcher owns the action worker, so no additional Sage or Iris process is created.
- Gmail action HTTP nodes use a literal body-enabled setting and n8n's native JSON-body mode. n8n marks `sendBody` as non-expression data, so a dynamic expression silently omitted Gmail's draft payload even though the preceding validator built it correctly.
- Tool-aware conversation permits at most two selection rounds, three total calls, and one mutation. This lets Sage search Calendar for an exact provider event ID before a follow-up update/delete selection while preserving bounded authority.
- The capability registry exposes Downloads filename search, managed-document search, and explicit copy-only import. Host discovery returns bounded metadata, skips symlinks, and stays within `/Users/hrudainirmal/Downloads`; Core performs the actual checksum-deduplicated copy into the managed registry and never alters the source.
