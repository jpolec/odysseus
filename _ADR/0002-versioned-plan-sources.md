---
status: Accepted
date: 2026-08-22
---

# ADR-0002: Bind plans to versioned requirement sources

## Context

A plan generated from a free-form prompt alone does not explain which ADR,
specification, issue, pull request, incident, or security finding authorized
each task. Re-running an already implemented decision can also waste compute
or accidentally repeat a delivered change.

## Decision

Odysseus accepts bounded repository documents, uploaded text files, GitHub
Issues and pull requests, and public HTTPS documents as Plan sources. Their
content, type, path, digest, and source-to-task references are frozen with the
Plan version.

Completed sources are shown as **Implemented**. They cannot create another Plan
unless the operator explicitly chooses **Force again**; that authorization is
stored with the frozen source. Task contracts can be filtered and sorted by
their linked source.

The default execution binding remains **Auto**. Agent, model, Skills,
environment, review policy, and required evidence remain separate fields so
routing outcomes can be measured without collapsing them into one model
selector.

## Consequences

- Requirement lineage is visible from source to task, evidence, and outcome.
- Duplicate content and likely secrets are rejected before durable storage.
- Public URL intake is HTTPS-only and rejects private or local destinations.
- Existing ADR files remain immutable inputs; completion state lives in the
  auditable Odysseus execution history.
- A forced repeat is possible, but never silent.
