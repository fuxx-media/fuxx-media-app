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

The suite covers login success/failure, expiry, revocation, CSRF, roles, tenant isolation, intake, MIME and size rejection, private upload/download, deduplication, parallel idempotency, queue locks/retry/terminal failure, workflow atomicity and immutable audit history. CI migrates an empty database twice before running tests.

Phase 2 additionally covers paginated and filtered worklists, cross-tenant hiding, assignment,
claim conflict/expiry/takeover, optimistic locking, immutable notes, checklist prerequisites,
self-approval and role rejection, revision-bound approval/rejection, approval invalidation,
evidence, worker restart recovery and persistent terminal queue failure.
