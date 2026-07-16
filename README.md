# MediaOS

MediaOS is a modular-monolith foundation for a later, human-approved media production workflow. This repository implements the Phase 0 infrastructure and workflow kernel: core persistence, atomic transitions, audit history, PostgreSQL task claiming, internal APIs, documentation, CI, and architecture enforcement.

No external AI provider, research workflow, media generation, publishing integration, multilingual system, or multi-tenant feature is implemented.

## Prerequisites

- Docker Desktop with a running Linux container engine
- Docker Compose
- Git
- Optional for host-side checks: Python 3.12, Node.js 22+, and npm

The supported and verified path is Docker Compose, so host Python is not required.

If local antivirus or enterprise TLS inspection replaces public certificates, export its public Windows root into the ignored local certificate directory before building:

```powershell
.\scripts\export_windows_root_ca.ps1 -CommonName "<verified root CA common name>"
$env:NODE_EXTRA_CA_CERTS = (Resolve-Path ".local-certs\local-root-ca.crt")
```

Do not disable TLS verification. The exported public CA is ignored by Git and is installed only in local images when present.

## Configure the current shell

Do not store real credentials in this repository. Set local-only values in the current PowerShell session:

```powershell
$env:POSTGRES_USER = "<local-user>"
$env:POSTGRES_PASSWORD = "<local-password>"
$env:POSTGRES_DB = "<local-database>"
$env:MINIO_ROOT_USER = "<local-admin-user>"
$env:MINIO_ROOT_PASSWORD = "<local-admin-password>"
$env:NEXT_PUBLIC_API_URL = "http://localhost:8000"
```

## Start

```powershell
docker compose --env-file .env.example config
docker compose --env-file .env.example up --build -d
docker compose --env-file .env.example ps
```

Local endpoints:

- Frontend: <http://localhost:3000>
- Backend health: <http://localhost:8000/api/v1/health>
- Backend readiness: <http://localhost:8000/api/v1/ready>
- Backend version: <http://localhost:8000/api/v1/version>
- MinIO API: <http://localhost:9000>
- MinIO console: <http://localhost:9001>

Stop without deleting persisted data:

```powershell
docker compose down
```

Deleting volumes is intentionally not part of the normal workflow.

## Quality checks

```powershell
docker compose run --rm backend ruff check backend/src backend/tests scripts
docker compose run --rm backend mypy backend/src scripts/check_architecture.py
docker compose run --rm backend pytest
docker compose run --rm backend python scripts/check_architecture.py
docker compose run --rm frontend npm run lint:frontend
docker compose run --rm frontend npm run typecheck:frontend
docker compose run --rm frontend npm run build:frontend
```

The GitHub-compatible workflow in `.github/workflows/ci.yml` runs the same categories of checks, including secret-pattern and forbidden-dependency checks.

`package-lock.json` is committed and both host and container installs use `npm ci`.

## Current scope

Phase 0 supplies health/readiness/version and workflow APIs, ten core entities, a database-aware queue worker, a minimal Next.js status page, PostgreSQL 16, MinIO, Alembic migrations, and CI enforcement. Real providers, content production, artifact upload, production identity integration, and publishing remain explicit non-goals.

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) and the files under [docs](docs) for authoritative scope and architecture decisions.
