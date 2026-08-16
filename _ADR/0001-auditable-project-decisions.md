---
status: Accepted
date: 2026-08-16
---

# ADR-0001: Keep project decisions in the repository

## Context

Requirements described only in prompts become difficult to discover, audit,
or connect to the work that implemented them. Repository-specific architecture
decisions should remain versioned with the code while Odysseus tracks their
execution history locally.

## Decision

Odysseus treats `_ADR/` as its recommended decision catalog and also discovers
common ADR folders. A selected decision is frozen by path, SHA-256 digest, and
content in an Epic proposal. Its approved tasks receive the same document in
their Context Receipt.

The repository Overview reports whether each decision is unplanned, proposed,
in progress, blocked, or completed, together with linked task counts, observed
tokens, and reported cost.

## Consequences

- Git remains the source of truth for the decision text.
- Planning remains read-only and requires explicit operator approval.
- Editing an ADR after planning does not rewrite the historical snapshot.
- Usage without provider-reported cost is shown as unknown, never as zero.
