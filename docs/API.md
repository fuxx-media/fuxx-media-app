# API

## Base path

All application endpoints use `/api/v1`.

## Implemented system endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/health` | Process liveness; no dependency claim |
| GET | `/api/v1/ready` | PostgreSQL and MinIO readiness |
| GET | `/api/v1/version` | Application name, version, and phase |

These endpoints are read-only and expose no secrets.

## Implemented workflow endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/channels` | Create a channel |
| POST | `/api/v1/jobs` | Create a content job |
| POST | `/api/v1/jobs/{id}/transitions` | Perform an atomic state transition |
| GET | `/api/v1/jobs/{id}/timeline` | Read transition history |
| GET | `/api/v1/jobs/{id}/costs` | Read integer-cent cost entries |
| GET | `/api/v1/jobs/{id}/audit` | Read the immutable audit trail |

Writes require `X-Actor-Id` and `X-Actor-Type` headers. This is a server-side Phase 0 boundary, not a claim of production identity integration. Errors consistently contain `code`, `message`, `details`, and `correlation_id`.

Artifact upload, provider execution, research, external AI, real publisher, and automatic-publication endpoints are explicit non-goals.
