---
name: security-review
description: Threat-model and review authentication, authorization, secrets, input boundaries, and dependency risk before declaring an engineering change complete.
triggers: security, authentication, authorization, auth, permission, rbac, oauth, password, passkey, token, session, secret, vulnerability, encryption, cryptography
---

# Security Review

Identify assets, trust boundaries, attackers, and abuse cases before editing. Preserve least privilege and deny-by-default behavior. Review input validation, output encoding, session lifecycle, secret handling, logging, and dependency exposure. Add focused negative tests for the highest-risk boundary. Report unresolved threats explicitly; do not weaken a control merely to make a test pass.
