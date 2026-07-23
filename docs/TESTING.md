# Testing

Integration tests refuse to run unless `POSTGRES_DB` ends in `_test` or `_ci_test` and `MEDIAOS_RUN_INTEGRATION=1`.

```powershell
# Create an isolated local test database in the PostgreSQL container.
docker compose exec postgres createdb -U <local-user> mediaos_phase1_test

docker compose run --rm --no-deps `
  -e POSTGRES_DB=mediaos_phase1_test `
  backend alembic -c backend/alembic.ini upgrade head

docker compose run --rm --no-deps `
  -e POSTGRES_DB=mediaos_phase1_test `
  -e MEDIAOS_RUN_INTEGRATION=1 `
  backend pytest backend/tests
```

The suite covers login success/failure, expiry, revocation, CSRF, roles, tenant isolation, intake, MIME and size rejection, private upload/download, deduplication, parallel idempotency, queue locks/retry/terminal failure, workflow atomicity and immutable audit history. CI migrates an empty database twice and runs `alembic check` to detect migration/model drift before running tests.

Phase 2 additionally covers paginated and filtered worklists, cross-tenant hiding, assignment,
claim conflict/expiry/takeover, optimistic locking, immutable notes, checklist prerequisites,
self-approval and role rejection, revision-bound approval/rejection, approval invalidation,
evidence, worker restart recovery and persistent terminal queue failure.

Phase 3 additionally tests the complete adapter contract, configuration validation, reference-only
secrets and masking, dry-run persistence/no effect/revision binding, business and technical gates,
required fields, atomic outbox creation, parallel idempotency and `SKIP LOCKED` claims, temporary and
permanent errors, timeout/rate-limit classification, retry limits/backoff, ambiguous status,
worker-restart recovery, dead letter, reasoned resume/discard, revision invalidation, callback HMAC,
expired timestamps, unknown correlation IDs, replay/double delivery, tenant/role boundaries and
provider audit completeness. Callback tests use an isolated process-only test secret and leave the
runtime callback feature disabled.

Hauptblock 6 adds signature-based JPEG/PNG/WebP/PDF/MP3/WAV/MP4 validation, size and empty-file
rejection, mismatch quarantine, SHA-256 deduplication, immutable versions, metadata extraction,
optimistic locking, tenant and role boundaries, version-bound approval, rights gates, Range preview,
cycle-safe relations, collections, deletion holds and durable media worker outcomes. Integration
tests use only a database ending in `_test` and an isolated MinIO test prefix/bucket. They must prove
that no anonymous policy exists, identical content has one binary reference and cleanup removes only
the test resources it created.

For an acceptance run, execute migration twice on a fresh isolated database, `alembic check`, the
complete Pytest suite, Ruff, strict Mypy, frontend format/lint/typecheck/production build,
`npm audit --omit=dev`, architecture and secret guards, Python sdist/wheel and Compose config. The
browser path covers upload, mismatch/duplicate information, metadata, rights, independent review,
new-version approval reset, preview/range/download authorization, relation-cycle rejection,
collection ordering, archive/deletion guards, audit and logout without console errors.
