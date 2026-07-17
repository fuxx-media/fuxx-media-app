# ADR 0005: Provider effects require approval, execution order and outbox

## Status

Accepted for Phase 3.

## Decision

Fachservices never import or call provider adapters. An external-capable action must be represented
by a current business approval, a separate technical approval, an immutable execution order and an
outbox row committed in one PostgreSQL transaction. Only the worker claims outbox rows with
`FOR UPDATE SKIP LOCKED` and invokes the adapter contract.

Provider, outbox, worker, retry and externally confirmed states remain separate. Normalized unknown
state is `AMBIGUOUS`, not success. Every attempt, response, result artifact, retry and intervention is
persistent and audited. Material case changes invalidate approvals and queued, not-started orders.

Phase 3 enables only `SimulationProvider`. Dry-run follows validation and preparation but creates no
outbox and records `external_effect=false`. Productive execution, real providers and callback intake
remain disabled. Configuration stores environment secret references only.

## Consequences

Later adapters must implement the established contract and cannot mutate domain entities. Adding a
real provider requires a separate reviewed phase, egress/security controls and explicit feature-flag
activation. PostgreSQL remains the authoritative recovery and idempotency source across restarts.
