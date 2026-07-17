# ADR 0004: Revision-bound internal case processing

## Decision

Keep `ContentJob` as the aggregate root and use its monotonic `version` as the business revision.
Human editing requires an expiring database claim and every mutation supplies `expected_version`.
Approval requests bind to the exact revision and become invalid when any material change creates a
new revision.

## Consequences

- Parallel edits and stale approvals fail with explicit conflict responses.
- The requester and last material editor cannot approve their own revision.
- Workers may execute only internal idempotent queue steps and cannot simulate human approval.
- Notes, audit events and revision snapshots are append-only and protected by database triggers.
- Phase 2 has no mail, publishing or external-provider effect.
