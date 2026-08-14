---
name: test-strategy
description: Build a proportionate deterministic test strategy covering behavior, regression risk, boundaries, integration seams, and flaky-test avoidance.
triggers: test, tests, testing, coverage, regression, unit, integration, e2e, playwright, flaky, fixture, assertion, verify
---

# Test Strategy

Start from observable behavior and the failure being prevented. Prefer the narrowest deterministic test that would fail before the change, then add integration coverage only at meaningful seams. Exercise error paths and boundary values. Avoid timing sleeps, implementation-detail assertions, and mocks that reproduce the implementation. Run the relevant existing suite and state what remains unverified.
