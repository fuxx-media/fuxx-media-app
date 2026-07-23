# Operations

## Start and migrate

```powershell
docker compose --env-file .env.example config --quiet
docker compose --env-file .env.example build
docker compose --env-file .env.example up -d
docker compose --env-file .env.example run --rm migrate
docker compose --env-file .env.example run --rm migrate
docker compose --env-file .env.example ps -a
```

The second migration run is intentional. `migrate` must exit 0; long-running services must be healthy.

## Create a local browser user

No default credential is committed. Supply a temporary process environment value only for the command:

```powershell
docker compose --env-file .env.example exec `
  -e MEDIAOS_BOOTSTRAP_PASSWORD='<local-only-password>' `
  backend python -m mediaos.cli create-local-user `
  --tenant-slug local-media `
  --tenant-name 'Local Media' `
  --email admin@example.com `
  --role ADMIN
```

Remove the shell variable after use. Production HTTPS must set `MEDIAOS_COOKIE_SECURE=true`.

## Runtime verification

Check `/health`, `/ready`, `/version`, frontend HTTP, worker heartbeat, `alembic current`, container logs and PostgreSQL rows for audit, idempotency and task state. Never use `docker compose down -v` as a routine operation.

## Rollback

Application rollback is a Git commit/image rollback. Migration downgrade exists for controlled non-production recovery, but production rollback must first preserve uploaded objects and database backup. New MinIO objects are transaction-compensated on intake failure.

## Phase 2 operations

Expired human claims can be taken over through the normal claim endpoint and are audited. The
worker recovers stale `RUNNING` queue claims after five minutes: retryable work returns to `RETRY`,
while exhausted work becomes persistent `FAILED`. Inspect `job_tasks.last_error` and matching
`QUEUE_TASK_COMPLETED`/`QUEUE_TASK_FAILED` audit events before manual intervention.

Real provider configurations must remain absent or disabled. Only the local simulation provider may
be enabled, and no mail, publishing or customer communication is part of this release.

## Phase 3 operations

Configure only the local simulation provider through the authenticated Admin UI. Supply
`MEDIAOS_SIMULATION_CALLBACK_SECRET` only in the local process environment when signed callback
tests are intentionally enabled; never store the value in Git or PostgreSQL. The persisted end state
must be: global integration active, simulation enabled, dry-run enabled, productive execution false,
real providers absent/disabled and callback intake false.

Inspect `execution_orders`, `outbox_events`, `execution_attempts`, `retry_plans`,
`provider_responses`, `result_artifacts` and provider-prefixed `audit_events` together. An ambiguous
status is not success. Manual resume and final discard are Admin-only, require a reason and append
audit evidence. After a worker restart, stale claims become retryable or dead-letter according to
their attempt limit. Do not manually rewrite started payloads or completed evidence.

## Hauptblock 6 media operations

Keep `MEDIAOS_MEDIA_UPLOAD_MAX_BYTES` bounded (default 104857600) and the configured media bucket
private. Do not add an anonymous MinIO policy. Upload object keys are content-addressed below the
authenticated tenant prefix; they must never be returned to the browser. Monitor `media_tasks` for
`VERIFY_MEDIA`, `REGISTER_PREVIEW` and `PURGE_MEDIA`, including attempts, retry time, lease and terminal
error. A quarantined file requires human review; do not rewrite its hash or verification state.

Backup and restore must treat PostgreSQL and the private MinIO bucket as one consistency unit. Record
the database backup time and MinIO snapshot/version, restore both to an isolated environment, run
`alembic upgrade head`, then verify every current `media_versions.media_file_id` against the stored
object size and SHA-256 before release. Never restore only object storage over a newer database.

Normal users may only request deletion. Admin approval still does not delete immediately: it creates
a worker task after retention-hold and active-relation checks. The worker rechecks references and
does not remove a shared binary while another non-purged version uses it. Inspect the audit events
before and after every purge. Do not delete volumes or objects manually during routine operation.

The accepted runtime flags keep public media, publishing, productive providers, real callbacks,
email and external media processing disabled. FUXX MEDIA Hauptblock 6 performs no network egress for
metadata extraction or previews.
