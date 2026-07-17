# Architecture

## System shape

MediaOS remains a modular monolith with separate runtime processes: Next.js frontend, FastAPI backend, PostgreSQL-backed worker, PostgreSQL 16 as the sole system of record, and private MinIO object storage. Alembic runs as a one-shot deployment gate before backend and worker start.

## Phase 1 trust boundaries

- The browser authenticates with tenant slug, email, and password.
- Passwords are stored only as Argon2id hashes.
- A random opaque session token is stored as a SHA-256 digest in PostgreSQL and sent only in an HttpOnly, SameSite=Strict cookie.
- A separate CSRF secret is bound to the server session. Mutating browser requests must present the matching cookie and `X-CSRF-Token` header.
- No authentication token is stored in Local Storage.
- `MEDIAOS_COOKIE_SECURE=false` is allowed only for local HTTP. HTTPS deployments must set it to `true`.
- API actors are derived from the persistent server session. Client-supplied actor headers are no longer accepted.

## Authorization and tenancy

Roles are `ADMIN`, `BACKOFFICE`, `REVIEWER`, and `SYSTEM_WORKER`. Write and review dependencies enforce the minimum role before application services run. Tenant identity comes from the authenticated user and is included in repository filters, jobs, channels, files, idempotency records, and audit events. A foreign tenant resource is returned as not found rather than disclosed.

## Intake transaction

`IntakeService` serializes equal idempotency keys with a PostgreSQL transaction advisory lock. Within the transaction it validates the tenant channel, creates the job in `DRAFT`, deduplicates a verified file by tenant and SHA-256, creates the attachment, appends an immutable audit event and enqueues `INTAKE_ACCEPTED`. The response is persisted in `idempotency_records` and replayed without a second effect.

MinIO cannot participate in the PostgreSQL transaction. New objects use content-addressed tenant paths and are removed by compensation if the database transaction fails. Existing deduplicated objects are never removed by a failed later request.

## Files

File content is checked by magic bytes or validated UTF-8 text, independently from the filename. Claimed MIME type must match detected content and size is capped before persistence. MinIO receives no public bucket policy. Downloads require a valid tenant session and append `FILE_DOWNLOADED` to the audit trail.

## Queue

Claims use `FOR UPDATE SKIP LOCKED`. Attempts are bounded. Failed attempts move to `RETRY`; the final failed attempt persists `FAILED` and `last_error`, which is the durable dead-letter state. No exception is converted to success.

## Module boundaries

- `domain`: entities and enums.
- `application`: authentication, idempotency, intake and workflow transaction boundaries.
- `infrastructure`: PostgreSQL repositories, queue and MinIO adapter.
- `api`: validation, session/CSRF dependencies, authorization and error mapping.
- `worker`: bounded task dispatch.

`scripts/check_architecture.py` enforces the repository allowlist, single-database rule, forbidden providers, secret patterns and exclusive workflow-state mutation authority.

## Phase 2 case processing

`ContentJob` remains the aggregate root. Its technical `current_state`, business-facing
`business_status`, queue status, approval status and provider state are separate dimensions.
`version` is the authoritative case revision and is checked on every material mutation.
`CaseProcessingService` owns row locks, claim expiry, optimistic version checks, approval
invalidation and append-only revision/audit writes.

Claims serialize human editing. Approval requests bind to one exact revision, may be claimed only
by a human Admin or Reviewer, and reject the requester or last material editor as reviewer. Notes
and case revisions are immutable in both ORM and PostgreSQL. Phase 2 creates internal queue events
only; no provider, mail, publishing or external URL path is called.

## Phase 3 provider boundary

No fachlicher service calls a provider adapter. The only permitted path is business decision,
revision-bound business approval, technical approval, immutable `ExecutionOrder` and
`ExecutionRevision`, atomic `OutboxEvent`, `SKIP LOCKED` worker claim, `ProviderAdapter`, normalized
response/result artifact, audit, and classified retry or dead letter.

Business approval, technical approval, execution status, outbox status, worker attempt, provider
status, retry state and externally confirmed result are independent. A later material case revision
invalidates technical approvals and queued/not-started executions; already started attempts retain
their immutable payload. The local `SimulationProvider` implements the same adapter contract as any
future provider (`validate_configuration`, `validate_request`, `prepare`, `execute`, `query_status`,
`cancel`, `normalize_response`, `classify_error`, `healthcheck`) but always records
`external_effect=false`.

Provider configuration persists references to environment secrets, never secret values. Callback
foundations use HMAC-SHA256, bounded timestamps, event replay protection and correlation IDs. Both
productive execution and callback intake are disabled by default and in the Phase-3 acceptance state.
