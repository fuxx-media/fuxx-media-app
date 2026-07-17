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

## Internal case processing

| Method | Path | Protection |
|---|---|---|
| GET | `/cases` | Session, tenant pagination and filters |
| GET | `/cases/{id}` | Session, tenant detail/history |
| POST | `/cases/{id}/claim` | Admin/Backoffice, CSRF, expected revision |
| POST | `/cases/{id}/claim/renew` | Claim owner, CSRF |
| POST | `/cases/{id}/update` | Claim owner, expected revision |
| POST | `/cases/{id}/notes` | Claim owner, immutable note |
| POST | `/cases/{id}/checklist` | Claim owner, one initial checklist |
| POST | `/cases/{id}/checklist/{item}` | Claim owner, expected revision |
| POST | `/cases/{id}/evidence` | Claim owner, tenant file or structured evidence |
| POST | `/cases/{id}/approval-requests` | Complete checklist, current revision |
| POST | `/cases/approvals/{id}/claim` | Human Admin/Reviewer, not self |
| POST | `/cases/approvals/{id}/resolve` | Human Admin/Reviewer, current revision |
| POST | `/cases/{id}/close` | Claim owner, approved current revision |

`GET /cases` accepts `page`, `page_size` (maximum 100), queue views (`open`, `mine`,
`unassigned`, `due`, `approval`, `rejected`, `completed`) and category, priority, status,
assignee and search filters. All tenant identity comes from the server session.
