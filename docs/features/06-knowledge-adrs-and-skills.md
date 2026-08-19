# 06 — Repository knowledge, ADRs, and Skills

Built across **Odysseus v0.5.0–v0.7.0**.

## The problem

Agents repeatedly rediscover a repository's architecture and local rules. A
prompt alone also does not reveal which README, instruction, ADR, memory, or
engineering procedure shaped the implementation.

## The guarantee

Odysseus discovers repository knowledge, lets the operator maintain private
project guidance, selects generic or project-local Skills, and records the
exact selected context in an immutable Context Receipt.

```text
task signals
   ↓
README + instructions + project brief + ADRs + memory + Skills
   ↓
ranked/selected context with paths and SHA-256 digests
   ↓
agent prompt + durable Context Receipt
```

Skills are engineering procedures such as security, database, API, testing,
accessibility, performance, incidents, dependencies, and documentation. They
do not grant filesystem, network, credential, or delivery permissions.

## Use it

- Open a repository's **Overview** to inspect its README, stack, instructions,
  recent Git history, project brief, memory, and available Skills.
- Put project decisions in `_ADR/`, `docs/adr/`, or another discovered ADR
  directory; see the [ADR guide](../PROJECT_DECISIONS.md).
- Set Skills to **Auto**, **Required**, or **Disabled**, or choose them manually
  under advanced task settings.
- Review repeated guidance before promoting it into project memory.

## Evidence to inspect

- Source path, byte count, content digest, and immutable snapshot.
- Why each Skill was selected and which version was loaded.
- Memory rule trigger and folder scope.
- ADR status, implementation status, linked Plan/tasks, and Plan history.
- Skill outcome, token, cost, retry, and intervention observations with sample
  size where enough data exists.

## Failure behavior

- Oversized, escaping, or invalid source documents are rejected.
- Missing context is visible rather than silently fabricated.
- Sparse Skill history does not produce a misleading success percentage.
- Changing a source after task start does not rewrite the task's receipt.

## Current boundary

This is provenance-aware repository context, not yet a native semantic code,
API, schema, ownership, or dependency graph. Learned causal Skill effects and
a portable Skills marketplace are deliberately deferred until trustworthy
outcomes and sufficient observations exist.

