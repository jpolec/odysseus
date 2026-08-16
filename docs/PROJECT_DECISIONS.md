# Project decisions and ADRs

Odysseus connects versioned architecture decisions to the agent work that
implements them.

## 1. Add an ADR to a repository

The recommended location is `_ADR/`:

```text
your-repository/
└── _ADR/
    ├── README.md
    ├── 0001-use-postgresql.md
    └── 0002-adopt-passkeys.md
```

Odysseus also discovers `ADR/`, `adr/`, `docs/adr/`, `docs/adrs/`, and
`docs/architecture/decisions/`. `README`, `index`, and template files are not
treated as decisions.

A minimal record is:

```markdown
# ADR-0002: Adopt passkeys

Status: Proposed
Date: 2026-08-16

## Context
Why this decision is needed.

## Decision
What must be true after implementation.

## Consequences
Trade-offs, migration, and rollback constraints.
```

## 2. Review the catalog

Choose the repository in the web UI. **Project Decisions** shows every detected
ADR, its recorded status, implementation state, linked task progress, observed
tokens, and reported cost.

Implementation states are literal:

| State | Meaning |
|---|---|
| Not planned | No Epic is linked to this ADR. |
| Plan ready | A task graph exists and waits for approval. |
| In progress | At least one approved task is running or waiting. |
| Blocked | Planning or an approved task graph failed. |
| Completed | Every linked task reached an accepted artifact or draft PR. |

## 3. Plan selected decisions

Select one or more ADRs and choose **Plan selected**. The Planner reads the
repository and the exact selected document snapshots, then proposes one
acyclic task graph. Inspect the graph and choose **Approve plan** before any
implementation task starts.

The Epic stores each source path, content, status, byte count, and SHA-256
digest. Every materialized task receives the same ADR snapshot in its Context
Receipt. Later edits to the repository file do not alter this history.

## 4. Understand completion and economics

Odysseus aggregates task states, input/output tokens, and provider-reported
cost across every Epic linked to the decision. Missing cost remains **Unknown**.
Use **View plan history** to inspect task DAGs and individual evidence.

ADR status and implementation status are intentionally separate. An
`Accepted` ADR can still be `Not planned`; an implemented ADR can later become
`Superseded` in Git without erasing its execution history.
