---
name: incident-debugging
description: Investigate crashes, regressions, production failures, and hard bugs through evidence preservation, hypothesis ranking, reproduction, and minimal repair.
triggers: bug, crash, failure, incident, error, regression, broken, debug, diagnose, timeout, deadlock, race, outage
---

# Incident Debugging

Preserve the failure evidence and timeline before changing code. Build a minimal reproduction, list competing hypotheses, and falsify the cheapest ones first. Trace from observable symptom to root cause rather than patching the final exception. Add a regression test that captures the causal boundary. Keep the repair narrow and document any remaining uncertainty or operational follow-up.
