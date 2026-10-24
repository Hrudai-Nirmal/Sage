# Chromium Observer Context

## Purpose

Collect permitted active-tab metadata and bounded semantic page extracts for Sage Core across Chromium profiles.

## Decisions

- Manifest V3 with a stable public extension key and incognito disabled.
- Exact extension Origin plus an ingress-only token authenticates loopback delivery.
- Navigation is immediate; active-page extraction is debounced for five seconds.
- YouTube reports one progress event only after 50% playback.
- Profile IDs are random local provenance identifiers, not user identities.

## Gotchas

- Never add clipboard, download, history, debugger, or native-messaging permissions.
- Never read form controls, editable content, captions, or comments.
- Hard exclusions run in both the extension and Core; neither boundary replaces the other.
- The extension badge is green when connected, amber when paused/unpaired, and grey when delivery fails.
