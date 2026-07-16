# API

## Base path

All application endpoints use `/api/v1`.

## Implemented in Phase 0.1

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/health` | Process liveness; no dependency claim |
| GET | `/api/v1/ready` | PostgreSQL and MinIO readiness |
| GET | `/api/v1/version` | Application name, version, and phase |

These endpoints are read-only and expose no secrets.

## Planned later in Phase 0

Channel, content-job, transition, timeline, cost, artifact, and audit endpoints from the master specification remain unimplemented. Future write routes will require authentication. All errors will use the specified `code`, `message`, `details`, and `correlation_id` envelope.

Publisher, research, external AI, and automatic-publication endpoints are explicit non-goals.

