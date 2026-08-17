# Odysseus invariants

Status: published registry for the frozen I01-I25 invariant set from
`docs/architecture/MASTER_PLAN.md`.

This document separates current guarantees from planned architecture. An
invariant marked `enforced` is backed by at least one focused automated test in
the machine-readable registry. An invariant marked `partial` describes current
0.8 behavior that supports part of the invariant, but it is not a complete
current guarantee. An invariant marked `planned` is target architecture only
and must not be described as implemented until it has focused automated tests.

Machine-readable registry: `docs/architecture/invariants.registry.json`.

| ID | Invariant | Status | Current guarantee or release target |
| --- | --- | --- | --- |
| I01 | Journal is canonical. | partial | NDJSON journals are durable and required by proof, but the full event-sourced journal is targeted for the 0.9 kernel. |
| I02 | A snapshot is a deterministic projection of the journal. | planned | Planned for the 0.9 kernel. Not a current 0.8 guarantee. |
| I03 | Every command is idempotent. | partial | Selected operations are idempotent; the universal command layer is targeted for the 0.9 kernel. |
| I04 | Every external side effect has durable intent before execution. | partial | Some operator decisions are recorded before effects; the durable outbox is targeted for the 0.9 kernel. |
| I05 | Every external side effect is reconcilable. | partial | Selected effects are reconciled; universal action reconciliation is targeted for the 0.9 kernel. |
| I06 | At most one valid worker lease exists for a node. | partial | Server leases and scheduler claim limits exist; per-node WorkerLease fencing is targeted for the 0.9 kernel. |
| I07 | An old worker cannot commit after lease takeover. | planned | Planned for the 0.9 kernel. Not a current 0.8 guarantee. |
| I08 | Accepted is not Published. | enforced | Acceptance records a local artifact and leaves delivery separate. |
| I09 | Published is not Integrated. | partial | Draft PR and integrated statuses are distinct; the full object model is targeted for the 0.9 kernel. |
| I10 | Integrated is not Deployed. | planned | Planned for a post-0.9 deployment milestone. Not a current 0.8 guarantee. |
| I11 | Deployed is not Healthy. | planned | Planned for a post-0.9 observation milestone. Not a current 0.8 guarantee. |
| I12 | A validator validates an immutable artifact SHA. | planned | Planned for the 0.9 kernel. Not a current 0.8 guarantee. |
| I13 | A validator cannot mutate the candidate it validates. | planned | Planned for the 0.9 kernel. Not a current 0.8 guarantee. |
| I14 | A router recommendation is not a routing decision. | enforced | Recommendations can remain shadow-only; automatic routing records when a lane is applied. |
| I15 | Missing evidence is not successful evidence. | enforced | Production proof excludes missing or misordered evidence from successful outcomes. |
| I16 | A missing metric is not zero. | enforced | Missing cost remains `None` or Unknown in proof and portfolio metrics. |
| I17 | A child policy can restrict but never widen a parent policy. | planned | Planned for the 0.9 policy model. Not a current 0.8 guarantee. |
| I18 | Every final outcome has lineage to a requirement and artifact. | partial | Context receipts, source documents, artifact SHAs, and proof receipts provide partial lineage; full OutcomeRecord lineage is targeted for the 0.9 kernel. |
| I19 | Every autonomous decision is explainable from stored evidence. | partial | Outcome routing explanations are stored; universal decision explanation is targeted for the 0.9 kernel. |
| I20 | State can be reconstructed after arbitrary process death. | partial | Durable snapshots, journals, and verification exist; full replay after arbitrary death is targeted for the 0.9 kernel. |
| I21 | Artifact bytes always match their immutable content hash. | planned | Planned for the 0.9 content-addressed ArtifactStore. Not a current 0.8 guarantee. |
| I22 | Approval applies to exactly one artifact, evidence, and contract tuple. | planned | Planned for the 0.9 ReviewDecision model. Not a current 0.8 guarantee. |
| I23 | Secrets never cross the durable persistence boundary unredacted. | partial | Selected redaction boundaries exist; the complete durable redaction engine is targeted for the 0.9 security boundary. |
| I24 | Historical domain-event bytes are never rewritten during schema evolution. | enforced | Snapshot migration preserves existing event journal bytes. |
| I25 | Duplicate inbound or outbound messages cannot cause duplicate logical effects. | partial | Selected inbound and delivery duplicates are deduplicated; universal message idempotency is targeted for the 0.9 kernel. |

## Registry rules

- IDs are frozen as `I01` through `I25`; new IDs require an update to the
  master plan.
- `enforced` means the registry has at least one valid focused automated test
  reference.
- `partial` must state the current narrow guarantee and the release that owns
  the remainder.
- `planned` must name its target release and must not be presented as a current
  guarantee.
- The coverage test in `tests/test_invariants.py` rejects unknown IDs,
  duplicate IDs, planned entries without target releases, and enforced entries
  without valid test references.
