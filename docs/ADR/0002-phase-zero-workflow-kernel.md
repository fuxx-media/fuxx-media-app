# ADR 0002: Phase 0 workflow kernel

## Status

Accepted.

## Decision

The Phase 0 workflow kernel is implemented inside the existing modular monolith. SQLAlchemy models and repositories share one PostgreSQL database. `WorkflowTransitionService` is the only state mutation authority and uses a row lock plus expected version. PostgreSQL job tasks are claimed with `FOR UPDATE SKIP LOCKED`.

Write APIs require a typed actor header pair as a temporary server-side Phase 0 boundary. This does not select a production identity provider.

## Consequences

State, transition, audit, and cost data commit atomically. Queue workers can claim tasks exclusively without a second queue technology. Production authentication, real providers, automatic publishing, and provider secrets remain outside Phase 0.
