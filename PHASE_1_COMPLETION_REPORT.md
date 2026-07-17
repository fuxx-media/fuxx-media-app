# Phase 1 completion report

Date: 2026-07-17

## Scope and source state

- Repository: `fuxx-media/fuxx-media-app`
- Branch: `codex/phase-1`
- Phase 0 baseline: `3ac5311`
- Authentication foundation: `b2c3a4e`
- Intake implementation: `92c5c64`
- Production deployment: not performed

## Repository governance

- Verified GitHub identity and repository administrator: `@fuxx-media`.
- `.github/CODEOWNERS` is valid according to GitHub's CODEOWNERS error API.
- The protected default branch is `main`.
- Protection requires a pull request, one approval, code-owner approval, dismissal of stale approvals, resolved conversations, strict up-to-date status checks, and administrator enforcement.
- Force pushes and deletion are disabled.
- Required checks use the observed GitHub Actions names: `Architecture and secret guard`, `Backend quality`, `Frontend quality`, and `Compose config`.

## Implemented

- Tenant-scoped users, roles, Argon2id password hashes, server-side sessions, expiry, revocation, login, logout, strict cookies, CSRF validation, and immediate rejection of sessions belonging to deactivated tenants.
- Server-derived actors and tenant/role enforcement on write and read routes; actor headers are no longer accepted as authentication.
- Persistent idempotency with transaction-scoped PostgreSQL advisory locks.
- Structured intake with optional private file upload, signature-based MIME validation, size limits, SHA-256, tenant-scoped deduplication, MinIO storage, atomic database records, initial workflow state, audit event, and queue task.
- Authenticated, tenant-authorized, audited downloads; anonymous MinIO reads remain denied.
- Atomic queue claims using `FOR UPDATE SKIP LOCKED`, bounded retry, and persistent `FAILED` state.
- Alembic revision `32df0ee0c2a1` and updated architecture, API, data model, threat model, operations, and test documentation.

## Docker recovery and persistence

- Initial symptom: Docker CLI operations against `desktop-linux` did not return.
- First exact backend error: `failed to dial docker daemon on desktop-linux context: unable to upgrade to h2c, received 500`.
- Stale build records also returned `lease ... not found` and remained at zero build steps.
- Recovery: project containers were stopped without removing them; Docker Desktop processes and WSL2 were stopped; `wsl --shutdown` was used; Docker Desktop was restarted; the engine was verified as `29.6.1`; stale BuildKit sessions were cleared by the controlled restart.
- Build context was reduced by excluding `.local-tools`; local CA certificates remain included because both Dockerfiles install them.
- Preserved volumes:
  - `fuxxmedia_postgres_data` -> `/var/lib/postgresql/data`
  - `fuxxmedia_minio_data` -> `/data`
- No volume, network, database volume, MinIO volume, or Compose project was deleted.
- The isolated database `mediaos_phase1_ci_test`, created only for this acceptance run, was removed after the successful tests; the application database was not modified by that cleanup.

## Fresh image and Compose proof

- Backend image: `sha256:ada81d5633d977ade94cfba72fb0405912ac68284c5ec90bb4d0882117451314`.
- Migration and worker tags reference the same freshly built backend artifact because all three services use the same Dockerfile.
- Frontend image: `sha256:4ce26b4703ed5f7ad25955303d0e517f48bd037b3da3951207c71351ac29a9ed`.
- Both distinct Dockerfiles were built with `--no-cache`.
- Compose recreate completed without `--volumes`; migration exited `0`; backend, frontend, worker, PostgreSQL, and MinIO were healthy.
- Alembic current and head: `32df0ee0c2a1`; repeated migration exited `0`.

## Acceptance evidence

- Empty isolated database migration: successful from zero through all three revisions; second upgrade successful.
- Pytest: `70 passed`.
- Ruff: passed.
- Mypy strict: passed, 32 source files.
- Frontend ESLint: passed with zero warnings.
- Frontend TypeScript: passed.
- Frontend production build: passed during the fresh image build.
- npm audit production dependencies: `0 vulnerabilities`.
- Architecture guard: passed.
- Python package build: sdist and wheel for `mediaos 0.2.0` built successfully.
- HTTP `/api/v1/health`, `/api/v1/ready`, and `/api/v1/version`: `200`.
- Anonymous protected route: `401`; reviewer write: `403`; missing CSRF: `403`.
- Login: `200`; logout: `204`; session after logout: `401`.
- Intake and upload: `201`; identical replay: `201`, same job id, `replayed=true`.
- Persistent idempotency record count for the proof job: `1`, response `201`.
- Queue task `87271c72-d3bc-4b0c-94bf-b55e23a4451b`: `SUCCEEDED`, attempts `1`, no error.
- Stored proof object: detected `application/pdf`, 30 bytes, 64-character SHA-256, private bucket; anonymous object request: `403`.
- Audit events for the proof job: `INTAKE_CREATED=1`, `FILE_DOWNLOADED=1`.
- Authenticated download: `200`, `application/pdf`, 30 bytes.
- Browser: Phase 1 UI ready, PostgreSQL and MinIO ready, login successful, logout displayed `Session widerrufen`, no console warnings or errors.

## Safety state

- No secret is committed; local proof credentials were process-only.
- No TLS verification bypass is present.
- Provider configurations remain disabled; no productive external provider or mail delivery was activated.
- The local proof tenant and proof records are explicitly named test evidence in the local development database; no production system was changed.

## Remaining release gate

The Phase 1 pull request must pass the four protected checks and receive a code-owner approval from an eligible reviewer before merge. The author cannot approve their own pull request; the protection rule must not be weakened to bypass that control.
