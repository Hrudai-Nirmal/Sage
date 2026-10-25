# Sage Observer Architecture

## Purpose

Observer is Iris's local-first ambient-awareness pipeline. It collects only permitted activity metadata and bounded extracts, converts related events into sessions, and creates evidence-backed observed or inferred memories for Sage. Observed content is evidence, never an instruction or authority to invoke a tool.

## Repository structure

```text
browser-extension/
  sage-observer/       Chromium Manifest V3 collector
src/sage_core/
  observer/            contracts, policy, session state, memory state, processing
macos/
  Sage/                SwiftUI operator app and native metadata observer
docs/
  observer-architecture.md
  observer-threat-model.md
tests/
  unit/                policy, normalization, sessions, consolidation
  integration/         authenticated ingress, persistence, retrieval
```

The existing FastAPI process remains the one durable state owner. The existing Iris model remains the sole background classifier. No additional model or agent process is introduced.

Core runs as a native LaunchAgent so it shares one macOS SQLite locking domain with the Telegram dispatcher. n8n remains in Docker and reaches the authenticated host boundary through Docker Desktop's host gateway; it never mounts or writes the database.

## Data flow

```text
Chromium extension / macOS app
        |
        | authenticated loopback event contract
        v
Observer ingress -> policy + redaction -> durable bounded queue
        -> session builder -> Iris structured analysis
        -> candidate validation -> consolidation
        -> observed / inferred memory + evidence
        -> FTS retrieval -> Sage conversation / macOS app
```

Collectors never call Sage tools. Iris receives bounded untrusted evidence and may return only the validated analysis schema. Core alone applies memory policy and persistence.

## Runtime policy

| Effective state | Collection | Iris processing |
|---|---|---|
| Normal | Enabled | Batched at session close, 50 events, or five idle minutes |
| Eco | Lightweight events | Deferred until idle and external power |
| Manual sleep | Disabled | Paused until explicitly resumed |
| Battery or Low Power Mode | Disabled immediately | Paused; restore prior mode only after external power and unlock |
| Shutdown | Disabled | Stopped with all Sage services |

An explicit Observer Off flag survives restarts and overrides Normal or Eco. Battery-forced sleep never changes that persisted preference.

## Browser communication

The Manifest V3 extension posts JSON to an HTTP loopback endpoint. Requests require:

- a separate observation-ingress bearer token with no read or mutation privileges;
- an exact `chrome-extension://<stable-extension-id>` Origin match;
- a schema-valid event identifier and timezone-aware timestamp;
- a bounded request body and bounded text fields;
- replay protection through the globally unique event identifier;
- Core-side URL normalization, denylist enforcement, and redaction.

The extension is loaded independently in each Chromium profile. `browserFamily`, `profileId`, and an optional user-editable profile label are provenance only. They never authorize browser automation or access to Google service credentials.

## Native desktop communication

The native app observes foreground application switches with `NSWorkspace` notifications and accessible window-title changes with AX notifications. It does not poll the screen. Browser, password/authentication, messaging, mail, and system-settings bundle identifiers are rejected locally before title access and rejected again by Core.

Permitted events contain a UUID, timezone-aware timestamp, host identity, event type, app bundle ID, app name, optional redacted window title, and optional active duration. App identity is stored on each event so later source-label changes cannot corrupt provenance. A separate write-only native ingress token authenticates this contract.

The app queues at most 1,000 events in a mode-`0600` disk FIFO and removes an item only after Core acknowledges it. Core or model downtime therefore does not block desktop use or discard permitted metadata. Battery, Low Power Mode, lock, Secure Input, Sleep, Shutdown, or Observer Off stop collection immediately.

## Event contract

Every event has these required fields:

- `eventId`: collector-generated UUID, used for idempotency;
- `eventType`: navigation, active-page, search, video-progress, idle, or resume;
- `occurredAt`: timezone-aware ISO 8601 timestamp;
- `browserFamily` and `profileId`;
- `url` and `title` when a page is involved.

Optional fields are narrowly bounded: cleaned page excerpt, active duration, search query, and YouTube metadata. Captions are transient Iris input and are never accepted by durable event ingress. Input values, selected text, clipboard contents, downloads, and keystrokes are not part of the contract.

## Session contract

Events are assigned transactionally to a source session. A session remains open across related activity and short application switches, closes after five idle minutes, and may merge a related return within ten minutes. Session identity is retained on every evidence edge so independent-session counts can be computed without trusting model output.

## Analysis contract

Iris returns strict JSON with:

- an activity category and concise session summary;
- zero or more directly observed entities;
- zero or more memory candidates;
- candidate kind, stable subject key, summary, confidence, reasoning, and supporting event IDs;
- entertainment and uncertainty flags.

Core rejects unknown fields, invalid event references, sensitive-trait inference, purchase-intent inference, tool/action instructions, and confidence outside `0..1`. Entertainment can create only short-lived minimal episodic memory. Uncertain classifications create explicitly uncertain, low-confidence memory as requested; they never become confirmed facts.

## Memory trust model

- `OBSERVED`: direct activity evidence, with source and timestamp.
- `INFERRED`: Iris interpretation supported by provenance, confidence, and independent-session count.
- `CONFIRMED`: existing `context_records`, written only through the established explicit or approval-gated paths.

Two qualifying independent sessions are required to create an inferred interest. Additional independent evidence updates that memory instead of creating duplicates. An inferred memory can never overwrite confirmed context. Promotion to confirmed memory is available only through an independent macOS approval.

## Storage and retention

Additive SQLite tables hold sources, normalized events, sessions, memories, evidence edges, and observer settings. SQLite FTS5 indexes memory summaries and subjects. Foreign keys protect source/session/evidence relationships; memory deletion removes evidence edges and FTS entries in one transaction.

- raw events: 30 days;
- cleaned extracts: 14 days;
- meaningful episodic summaries: one year;
- trivial entertainment episodes: 30 days;
- confirmed or user-selected episodes: indefinite;
- inferred interest without new support: delete after 30 days, retaining only a content-free audit event.

The queue is bounded to 50,000 events or 500 MB. Overflow removes the oldest low-value raw records first and increments a content-free audit counter.

## Retrieval

Retrieval supports keyword/FTS queries and filters for time, entity, activity, memory kind, and trust level. Conversation injection is query-relevant and bounded to eight inferred plus four episodic memories. Results always label trust, date, confidence where applicable, and evidence provenance.

## Implemented vertical slices

The first shippable path uses synthetic extension events before real browsing:

1. authenticate and validate an event;
2. normalize, redact, deduplicate, and persist it;
3. attach it to a durable session;
4. process the session through an injected Iris-compatible analyzer;
5. consolidate two independent qualifying sessions into one inferred memory;
6. retrieve it through FTS with both evidence references;
7. verify excluded content, replay, deletion, and model failure behavior.

The browser path and native metadata path are implemented. The native path includes the menu-bar/window controls, power policy, app/title observation, queue recovery, independent authentication, and per-event app provenance. Screenshot capture, Apple Vision OCR, selective Iris vision analysis, semantic embeddings, and the memory inspection/correction UI remain future slices.
