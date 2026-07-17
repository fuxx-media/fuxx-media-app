# MediaOS

MediaOS is a modular-monolith foundation for a human-approved media production workflow. Phase 2 adds tenant-safe worklists, expiring edit claims, classification, checklists, internal notes and evidence, revision-bound four-eyes approval, audit history and durable internal worker continuation to the Phase 1 authenticated intake.

No external AI provider, research workflow, media generation or publishing integration is activated.

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

Create a local user only with an ephemeral password supplied to the process:

```powershell
docker compose --env-file .env.example exec `
  -e MEDIAOS_BOOTSTRAP_PASSWORD='<local-only-password>' `
  backend python -m mediaos.cli create-local-user `
  --tenant-slug local-media --tenant-name 'Local Media' `
  --email admin@example.com --role ADMIN
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
docker compose run --rm -e POSTGRES_DB=mediaos_phase2_test -e MEDIAOS_RUN_INTEGRATION=1 backend pytest
docker compose run --rm backend python scripts/check_architecture.py
docker compose run --rm frontend npm run lint:frontend
docker compose run --rm frontend npm run typecheck:frontend
docker compose run --rm frontend npm run build:frontend
```

The GitHub-compatible workflow in `.github/workflows/ci.yml` runs the same categories of checks, including secret-pattern and forbidden-dependency checks.

`package-lock.json` is committed and both host and container installs use `npm ci`.

## Current scope

Phase 2 supplies provider-independent internal processing from authenticated intake through a revision-safe decision. The frontend exposes real lists, details, claims, checklists, notes, evidence and approval actions without Local Storage tokens. Real providers, customer communication, content production and publishing remain explicit non-goals.

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md), [docs/OPERATIONS.md](docs/OPERATIONS.md), [docs/TESTING.md](docs/TESTING.md), and [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md).
