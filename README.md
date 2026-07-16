# MediaOS

MediaOS is a modular-monolith foundation for a later, human-approved media production workflow. This repository currently implements **Phase 0.1 only**: repository structure, runtime skeletons, local infrastructure, documentation, CI foundations, and architecture enforcement.

No external AI provider, research workflow, media generation, publishing integration, multilingual system, or multi-tenant feature is implemented.

## Prerequisites

- Docker Desktop with a running Linux container engine
- Docker Compose
- Git
- Optional for host-side checks: Python 3.12, Node.js 22+, and npm

The supported and verified path is Docker Compose, so host Python is not required.

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
docker compose config
docker compose up --build -d
docker compose ps
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
docker compose run --rm backend ruff check backend scripts
docker compose run --rm backend mypy backend/src scripts/check_architecture.py
docker compose run --rm backend pytest
docker compose run --rm backend python scripts/check_architecture.py
docker compose run --rm frontend npm run lint:frontend
docker compose run --rm frontend npm run typecheck:frontend
docker compose run --rm frontend npm run build:frontend
```

The GitHub-compatible workflow in `.github/workflows/ci.yml` runs the same categories of checks, including secret-pattern and forbidden-dependency checks.

`package-lock.json` is intentionally expected once npm registry access is healthy. Until then, the frontend install path falls back to `npm install` so the skeleton can still be built in an environment where npm can reach the registry.

## Current scope

Phase 0.1 supplies a FastAPI skeleton with health/readiness/version endpoints, a database-aware Python worker skeleton, a minimal Next.js internal status page, PostgreSQL 16, MinIO, Alembic infrastructure, and CI enforcement. Domain models, workflow transitions, the PostgreSQL job queue, provider interfaces, and business APIs remain planned work in later Phase 0 work packages.

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) and the files under [docs](docs) for authoritative scope and architecture decisions.
