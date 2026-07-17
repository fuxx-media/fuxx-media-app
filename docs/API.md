# API

All endpoints use `/api/v1`. Errors contain `code`, `message`, `details`, and `correlation_id`.

## Public system endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Process liveness |
| GET | `/ready` | PostgreSQL and MinIO readiness |
| GET | `/version` | Version and phase |

## Authentication

| Method | Path | Protection |
|---|---|---|
| POST | `/auth/login` | Tenant slug, email, password |
| GET | `/auth/me` | Session cookie |
| POST | `/auth/logout` | Session cookie and CSRF |

Login sets `mediaos_session` as HttpOnly and `mediaos_csrf` as a browser-readable CSRF cookie. The response also returns the CSRF value for an in-memory client state. Logout revokes the database session before cookies are removed.

## Workflow and intake

| Method | Path | Protection |
|---|---|---|
| POST | `/channels` | Admin/Backoffice, CSRF, `Idempotency-Key` |
| POST | `/jobs` | Admin/Backoffice, CSRF, `Idempotency-Key` |
| POST | `/jobs/{id}/transitions` | Admin/Backoffice/Reviewer, CSRF, expected version |
| GET | `/jobs/{id}/timeline` | Authenticated tenant |
| GET | `/jobs/{id}/costs` | Authenticated tenant |
| GET | `/jobs/{id}/audit` | Authenticated tenant |
| POST | `/intakes` | Admin/Backoffice, CSRF, `Idempotency-Key` |
| GET | `/files/{id}/download` | Authenticated tenant, audited |

`POST /intakes` uses multipart form fields `channel_id`, `title`, `budget_limit_cents`, and optional `upload`. A successful response contains `job_id`, optional attachment/file IDs, `queue_task_id`, and `replayed`. Reusing the same key and payload returns the original identifiers. Reusing a key for a different payload returns `IDEMPOTENCY_CONFLICT`.

No endpoint accepts `X-Actor-Id` or `X-Actor-Type`.
