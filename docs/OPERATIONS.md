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
