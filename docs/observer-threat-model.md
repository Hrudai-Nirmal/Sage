# Sage Observer Threat Model

## Trust boundaries

1. Browser and desktop content is untrusted and may contain prompt injection or secrets.
2. Collector processes may submit observations but cannot read memory or invoke tools.
3. Iris may classify evidence but cannot approve, mutate confirmed context, or invoke tools.
4. Core validates every candidate and owns persistence.
5. Sage retrieves bounded memories but receives no authority from their content.
6. Only the user can approve promotion to confirmed memory or destructive Telegram actions.

## Collection controls

- Incognito/private browsing is disabled at the extension manifest boundary.
- Password, payment, authentication-secret, and private-session exclusions cannot be overridden.
- Banking, healthcare, identity, webmail message, messaging, remote-desktop, and security-settings surfaces are denied by default.
- Native browser capture is suppressed unless the extension confirms that the active tab is permitted.
- Lock, secure input, uncertain permission state, battery, and Low Power Mode all fail closed.
- Screenshot files are temporary and removed immediately after OCR or Iris processing.

## Ingress controls

- Bind only to loopback.
- Require an ingress-only secret and exact extension Origin.
- Validate type, size, timestamp, URL scheme, and identifiers before persistence.
- Normalize URLs and remove tracking parameters.
- Redact likely credentials and search-query secrets before writing.
- Reject durable caption text, form values, data URLs, browser-internal URLs, and unsupported event types.
- Deduplicate by event identifier and apply bounded request rate and queue limits.

## Model controls

- Wrap observed content as data under a fixed Iris system contract.
- Require schema-valid JSON; reject free-form instructions and unknown fields.
- Validate every supporting event ID against the current session.
- Prevent sensitive-trait and purchase-intent inference in deterministic Core policy.
- Label uncertainty rather than upgrading it to fact.
- Keep tool registries and approval credentials out of Iris requests.

## Storage controls

- Store all Observer data under the private Sage data root with owner-only permissions.
- Keep the SQLite database authoritative and use foreign keys for provenance.
- Keep temporary artifacts under `observer/temp` and remove them on success, failure, or shutdown.
- Apply retention independently to raw evidence and durable memory.
- Remove retrieval indexes and evidence edges atomically with a forgotten memory.
- Never log full extracts, tokens, or screenshot content.

## Known limitation

Accessibility, OCR, and visual filtering cannot guarantee that a secret is never visible. The design therefore prioritizes excluding sensitive windows before capture, bounding retained extracts, local redaction, short retention, and user-visible pause/off controls.
