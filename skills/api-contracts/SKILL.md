---
name: api-contracts
description: Change HTTP, event, RPC, webhook, and library interfaces while preserving explicit contracts, compatibility, validation, and failure semantics.
triggers: api, endpoint, http, rest, graphql, grpc, webhook, event, contract, request, response, client, serialization, protocol
---

# API Contracts

Identify consumers and the current request, response, error, pagination, and versioning contract before editing. Prefer additive compatible changes. Validate at the boundary and keep internal errors from leaking sensitive details. Update contract tests and documentation together. If a breaking change is necessary, provide an explicit migration path and compatibility window.
