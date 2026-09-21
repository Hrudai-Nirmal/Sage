# Sage

Sage is a single-user, local-first personal operations assistant for macOS. Telegram will be its conversation interface; the local operator interface covers system controls, state, approvals, documents, audits, and backups.

## Current foundation

- Native MLX-VLM model services are verified with Sage (`Qwen3.5-9B-6bit`) and Iris (`Qwen3-VL-2B-Instruct-4bit`).
- Sage Core is a FastAPI + SQLite service with durable modes, task/case/schedule approval gates, retryable scheduled delivery, separate proposal/approval/operator credentials, an audit trail, and an allowlisted Telegram ingress boundary.
- Online research uses Tavily basic search plus local Trafilatura extraction, with bounded source counts, public-network URL checks, durable citations, and retrieval audit events.
- Versioned role contracts in `prompts/` define Sage's user-facing authority and Iris's restricted background-analysis role. The dispatcher loads Sage's prompt for every model call.
- Ordinary Telegram conversation uses a closed capability registry. Sage may select only implemented Gmail, Calendar, and Drive tools; deterministic validation and policy code executes each call, and the model receives the bounded result for its final answer.
- A code-owned capability broker injects Sage's complete configured ability and authority manifest into every model turn. It permits automatic inference of one read-only source, asks when multiple sources are named, retries only technical failures on retry-safe operations at most three times, and blocks model claims that configured integrations do not exist.
- Confirmed personal context is stored in a typed, provenance-aware SQLite registry with immutable revisions. Private generated Markdown views under `SageData/context` make ordinary context inspectable; sensitive values remain only in SQLite and the Markdown registry exposes metadata alone. Relevant confirmed records are injected into every Sage model turn; conversation guesses are never silently promoted to memory.
- Telegram images and image/PDF documents are bounded at 20 MB, inspected by Iris, synthesized by Sage, and removed from temporary storage after each request.
- Docker Compose defines local-only Sage Core and n8n services. Native launchd templates own model services.
- The managed data root is `/Users/hrudainirmal/SageData`; all runtime state and secrets are excluded from Git.

Telegram routing is configured privately for the chosen forum group. The active Telegram poller is ingress-only; one native dispatcher owns all replies, scheduled deliveries, Calendar reminders, email triage, Drive jobs, and model calls. Gmail is checked every five minutes, Calendar every 30 minutes, and Drive only on demand.

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
Open the local operator dashboard at [http://127.0.0.1:8787/operator](http://127.0.0.1:8787/operator) to inspect modes, approvals, tasks, cases, documents, research, schedules, and audit activity. Conversation remains in Telegram.

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

Google commands in Telegram use the following boundaries:

- `/mail [terms]` searches Gmail snapshots from all four accounts. Natural requests such as “check my mail for an H&M purchase,” “do I have email from Neon,” and “check recent notifications from Neon and Inngest” use the same real search path.
- `/calendar [terms]` searches personal-work Calendar events.
- `/drive [terms]` searches all four Drives live and returns Google view links.
- `/drive-folder work | Applications` creates a folder in the named account.
- `/drive-rename personal | <file-id> | Final.pdf` renames one exact Drive item.
- `/drive-delete college | <file-id> | Draft.pdf` creates a deletion approval card; deletion cannot run before approval.

The slash commands are deterministic shortcuts, not the only interface. Ordinary phrasing can select the same registered capabilities through Qwen's native function calling. A turn may make at most three reads and at most one mutation; Drive mutations still require explicit user wording, and Drive deletion still produces the independent Telegram approval button instead of executing directly.

Ordinary chat also supports explicit Google actions with complete details:

- Gmail sending is available from any configured account, but every message is shown in a one-time Telegram approval card. Approval creates a durable two-stage outbox job: first a Gmail draft is created, its remote ID is saved, and only then is that exact draft sent.
- Email composition is versioned locally before sending: revisions are immutable, old approval cards are superseded, and every approval is tied to one exact draft version. Active draft status is visible in Sage Operator.
- Calendar creation and updates are queued only for the personal-work account when the event target and timezone-aware times are explicit. Sage never guesses missing event details.
- Calendar deletion always creates a one-time Telegram approval card. Approved Calendar operations use a durable retry queue, and creates use a stable Google event ID so retries do not duplicate the event.
- The local operator dashboard shows pending Google outbox stages and retry counts without exposing email bodies.

Document handling is also available through ordinary Telegram phrasing. Sage can search filename metadata in the allowlisted `/Users/hrudainirmal/Downloads` tree, search its managed document registry, and copy one exact requested Downloads file into `/Users/hrudainirmal/SageData/documents/general`. It skips symlinks, rejects absolute and parent-traversal paths, never modifies the source, deduplicates imported content by SHA-256, and returns only the managed document ID/name/checksum to the model.

Personal context is available through ordinary explicit requests and deterministic commands:

- `/context [terms]` lists matching confirmed records with the exact ID and version needed for later changes.
- `/remember <category> | <key> | <value>` creates or revises a record. `preferences`, `projects-commitments`, and `user-rules` are ordinary records. `identity`, `people`, `education-work`, `owned-items`, and `important-dates` always produce an approval card.
- `/correct <record-id> | <new-value>` revises the exact record. Sensitive corrections remain approval-gated.
- `/forget <record-id>` always creates an approval card. Approval removes the managed JSON file and redacts the value from both the active row and its retained revisions.

Sage can search confirmed context automatically and receives a bounded relevant-context block for ordinary chat, research synthesis, attachment synthesis, and scheduled reports. Explicit writes are replay-safe, every revision keeps its source and actor, stale approvals cannot overwrite a newer record, and the local operator dashboard exposes the active registry for review. If Sage merely thinks something may be worth remembering, it must suggest an exact `/remember` command instead of persisting the inference.

Gmail polling never marks email read or changes labels/archives; outbound mail runs only through the separately approved outbox. Each account is polled independently, so an expired OAuth credential cannot block the other three accounts. Clear security, billing, placement, and deadline messages can trigger Notifications, which identify the receiving account. Placement matching includes placement/career offices, campus hiring, application status, interview logistics, shortlisting, and offers. Suggested tasks remain approval-gated. Calendar creates deterministic reminders 10 minutes before timed events. Drive is never monitored in the background.

n8n stores failed runs for diagnosis but skips successful poll payloads. Its built-in retention keeps no more than 1,000 executions or seven days and continuously removes expired execution data to prevent local database buildup.

The static Google OAuth disclosure site under `site/` publishes Sage's homepage, privacy policy, terms, and Limited Use statement at `https://sage.hrudainirmal.in`. It is intentionally separate from the local application and contains no tracking or connection to private Sage data.

Send a photo, JPEG/PNG/WebP document, or PDF in Main for Iris-assisted analysis. PDFs currently analyze the first rendered page. Telegram-reported sizes are checked when present and downloaded bytes are always capped at 20 MB; temporary files are deleted after the request.

Create approval-gated scheduled work with:

```text
/schedule 2026-09-11T09:00:00+05:30 | REPORT | Morning plan | Summarize my open tasks | DAILY
/schedule 2026-09-11T18:00:00+05:30 | NOTIFICATION | Placement deadline | Submit the placement form
```

The recurrence suffix is optional and accepts `DAILY` or `WEEKLY`. Reports use the current durable task/case snapshot and go to Scheduled Reports; notifications go to Notifications. Sleep and Shutdown preserve overdue work as backlog. Normal and Eco deliver it after Sage is available, and transient failures retry with bounded backoff.

## Verification

```zsh
/Users/hrudainirmal/SageData/runtime/sage-core/bin/python -m pytest -q
```

## Security boundaries

- Sage never writes to external source folders; future imports copy into the managed data root.
- Task, case, skill, and workflow changes are designed to use one-time user approvals. Core distinguishes the agent proposal channel from the approval channel.
- Telegram messages are accepted only from the configured numeric user and Sage forum topics; retrying the same Telegram message ID is safe.
- n8n only ingests allowlisted Telegram updates. The single native dispatcher is the sole owner of Telegram replies and Sage model calls.
- `/task <title>`, `/case <title> | <objective>`, and `/schedule ...` return Telegram approval cards. Only the configured user's one-time Approve or Decline callback can resolve the proposal.
- Secrets have mode `0600` under `/Users/hrudainirmal/SageData/secrets` and are not tracked by Git.
- Model services and Docker application ports are loopback-only.
- A model server never starts when its reserved port belongs to another process; a matching existing server is reused instead of duplicated.
- Online fetches accept only HTTP(S), reject credentials in URLs and non-public resolved addresses, validate redirects, cap pages at 2 MB, and retain at most 30,000 extracted characters per source.
