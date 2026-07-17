# MediaOS implementation plan

## Scope and interpretation

This plan covers the verified Phase 0 kernel, completed Phase 1 persistent intake and Phase 2 internal case processing. Provider execution remains outside the current scope.

No technical contradiction blocks Phase 0.1. Two specification details are resolved conservatively:

1. The repository tree is illustrative where later sections explicitly require additional files.
2. GitHub ownership is bound to the verified `fuxx-media` account and enforced by branch protection.

## Phase 1 – persistent authenticated intake (completed)

- Persistent tenants, users, roles and revocable server-side sessions.
- Argon2id password hashes, HttpOnly session cookies and bound CSRF tokens.
- Server-derived actor identity and tenant-scoped authorization for all protected APIs.
- Durable idempotency with parallel-request serialization.
- Content-verified, size-limited private MinIO uploads with SHA-256 deduplication.
- Atomic job, audit and queue creation with object-storage compensation.
- Authenticated audited downloads and bounded queue failure handling.
- Empty-database and repeated Alembic migration proof, security and browser tests.

## Phase 2 – revision-safe internal case processing (completed)

- Tenant-safe paginated worklists and detail views with real database state.
- Assignment, expiring atomic claims, takeover and optimistic version conflict handling.
- Classification, priority, wiedervorlage, immutable notes, checklists and evidence.
- Revision-bound approval request, reviewer claim, rejection, approval and invalidation.
- Server-side self-approval and stale-revision prevention.
- Persistent worker recovery, bounded retry, terminal failure and audit events.
- No mail, publishing, provider calls or other productive external effect.

## Work package 0.1 – repository and infrastructure

### Deliverables and files

- Root: `README.md`, `.env.example`, `.gitignore`, `.dockerignore`, `docker-compose.yml`, `Makefile`, `pyproject.toml`, `package.json`
- Governance: `docs/*`, `.github/*`, `scripts/check_architecture.py`
- Runtime skeletons: `backend/src/mediaos/*`, `frontend/*`
- Database infrastructure: `backend/alembic.ini`, `backend/migrations/*`
- Tests: skeleton smoke, configuration, API health, and security tests

### Order

1. Establish the repository and documentation.
2. Add Docker Compose and container build files.
3. Add backend and worker skeletons sharing one Python package.
4. Add the minimal frontend skeleton.
5. Add CI and architecture checks.
6. Run lint, type checks, tests, image builds, Compose start, API/browser-level HTTP smoke tests, service-state checks, and log checks.

### Risks and controls

- Secret leakage: only placeholders are committed; runtime credentials are process environment variables.
- Dependency creep: CI and `scripts/check_architecture.py` reject forbidden packages.
- Scope creep: domain and workflow modules remain package boundaries without Phase 0.2+ behavior.
- Runtime drift: Python and PostgreSQL major versions are fixed; dependency lock files record frontend resolution.
- Destructive local operations: normal commands never delete Docker volumes.

### Definition of done

- Required repository structure and documentation exist.
- Docker Compose configuration validates.
- PostgreSQL, MinIO, migration, backend, worker, and frontend containers start.
- Backend health/readiness/version and frontend root return successful HTTP responses.
- Worker reports a database-backed heartbeat; it does not claim job-queue support.
- Ruff, Mypy, Pytest, ESLint, TypeScript, backend build, frontend build, and architecture checks pass.
- The 32 rules are documented and mapped to automated or review enforcement.
- No prohibited Phase 0 feature is present.

## Work package 0.2 – core data model (completed)

### Files

- `backend/src/mediaos/domain/`: typed enums and domain entities
- `backend/src/mediaos/infrastructure/`: SQLAlchemy repositories
- `backend/migrations/versions/`: idempotent schema migration
- `backend/tests/unit/` and `backend/tests/integration/`: model, constraint, and migration tests

### Definition of done

- All ten required entities use UUID primary keys, UTC timestamps, and integer cents where applicable.
- `ContentJob` has optimistic concurrency control.
- Duplicate and constraint conditions are checked before database enforcement.
- Migration rerun and target-database verification pass.

## Work package 0.3 – workflow and audit (completed)

### Files

- `backend/src/mediaos/application/workflow_transition_service.py`
- workflow policy, prerequisites, audit persistence, and unit/integration tests

### Definition of done

- All state mutation occurs only through `WorkflowTransitionService`.
- Allowed, forbidden, version-conflict, prerequisite, and cost-limit cases are tested.
- Transition, version increment, workflow record, and immutable audit event commit atomically.

## Work package 0.4 – PostgreSQL queue and worker (completed)

### Files

- Queue repository and worker handlers under `backend/src/mediaos/`
- task migration and concurrency/retry tests

### Definition of done

- Claiming uses `FOR UPDATE SKIP LOCKED` in a transaction.
- Parallel workers cannot claim the same task.
- Success/failure result and audit event are persisted; retries are bounded and tested.

## Work package 0.5 – Phase 0 API (completed)

### Files

- Versioned FastAPI routers, schemas, authentication, and uniform errors under `backend/src/mediaos/api/`
- API and authorization tests

### Definition of done

- All specified endpoints exist; write endpoints require authentication.
- 404, validation, version conflict, invalid transition, and secret-redaction tests pass.
- No publisher, research, AI, or automatic-publication endpoint exists.

## Work package 0.6 – internal frontend (completed in Phase 2)

### Files

- Dashboard, job list, job detail, typed API client, and tests under `frontend/`

### Definition of done

- Required counts, job fields, timeline, costs, audits, and artifacts are visible from real API data.
- Loading, partial, failed, blocked, and empty states reflect server truth.
- Authorization is enforced server-side; UI hiding is not treated as access control.

## Work package 0.7 – provider interfaces and fake adapters (not part of the current implementation)

### Files

- Provider protocols, registry, fake adapters, call records, and tests

### Definition of done

- Six required provider interfaces and fake adapters exist.
- Providers cannot mutate workflow state or own transactions.
- Registry behavior and fake calls are tested; no external provider SDK is installed.

## Work package 0.8 – final quality and completion (completed for this execution block)

### Files

- Expanded tests, finalized documentation, and `PHASE_0_COMPLETION_REPORT.md`

### Definition of done

- All 22 Phase 0 completion criteria have concrete test or runtime evidence.
- CI and architecture checks pass from a clean checkout.
- Running commit, migrations, services, feature flags, limitations, and rollback path are documented.
