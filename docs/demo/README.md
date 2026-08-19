# Odysseus product films

The main README uses the fast 45-second tour. Four focused films show individual
operator workflows without turning the README into a wall of embedded media.

| Film | What it shows |
| --- | --- |
| [45-second tour](odysseus-45s.mp4) | The complete repository-to-delivery loop at launch pace. |
| [Task → verified artifact](odysseus-task.mp4) | Choose a repository, describe an outcome, reveal optional controls, review evidence. |
| [Plan/DAG → parallel agents](odysseus-plan.mp4) | Requirement, approval-gated Plan, dependency graph, attention gate. |
| [Needs You → recovery → terminal](odysseus-recovery.mp4) | Decision queue, contextual guidance, CI repair, terminal handoff. |
| [Evidence → delivery → portfolio](odysseus-delivery.mp4) | Review, Context Receipt, merge risk, explicit delivery, outcome economics. |
| [Full 90-second tour](odysseus-90s.mp4) | The slower complete source walkthrough. |

The recording uses only the disposable state produced by `scripts/demo.py`.
It does not invoke a coding agent, consume model tokens, or read the operator's
Odysseus state.

Rebuild the complete suite from the repository root:

```sh
scripts/capture-web-video-suite.sh
```

The script derives the fast hero from the full source tour and captures each
focused workflow independently. To rebuild only the full source tour, run
`scripts/capture-web-demo.sh`.
