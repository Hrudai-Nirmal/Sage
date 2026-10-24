# Observer Module Context

## Purpose

Normalize permitted ambient activity, group it into durable sessions, and store evidence-backed observed or inferred memories without granting observed content any action authority.

## Decisions

- Core owns normalization, redaction, session assignment, consolidation, and retrieval.
- Collector event IDs are globally idempotent.
- Browser profile identity is provenance only.
- Two independent sessions are required for ordinary inferred semantic memory.
- Entertainment candidates never create semantic interests.
- FTS rows are maintained transactionally with memory rows.

## Gotchas

- Never accept captions as a durable browser-event field.
- Never infer purchase intent or protected/sensitive personal traits.
- Evidence IDs returned by Iris must belong to the session being analyzed.
- A model-generated confidence cannot promote an inference to confirmed context.
