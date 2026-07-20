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

## Provider foundation

| Method | Path | Protection |
|---|---|---|
| GET | `/providers` | Authenticated tenant; masked references only |
| POST | `/providers/simulation` | Admin, CSRF; no secret value accepted |
| POST | `/providers/{id}/technical-approvals` | Admin, CSRF, current approved revision |
| POST | `/providers/{id}/dry-runs` | Admin/Backoffice, CSRF, `Idempotency-Key` |
| POST | `/providers/{id}/executions` | Admin/Backoffice, CSRF, approvals, `Idempotency-Key` |
| GET | `/executions` | Authenticated tenant |
| GET | `/executions/{id}` | Authenticated tenant, attempts/outbox/results/audit |
| POST | `/executions/{id}/resume` | Admin, CSRF, mandatory reason |
| POST | `/executions/{id}/discard` | Admin, CSRF, mandatory reason |
| POST | `/provider-callbacks/{provider}` | Feature gate plus HMAC/timestamp/replay/correlation checks |

Dry-runs persist the same masked preparation payload without creating an outbox or external effect.
Simulation executions create the order and outbox atomically and are the only enabled adapter path.
API responses expose secret-reference metadata but never resolved secret values.

## Hauptblock 6 media library

All mutations below require an authenticated database session, matching CSRF cookie/header, a
server-derived tenant, an allowed role, an expected aggregate revision where applicable and an audit
event. Re-playable creates additionally require `Idempotency-Key`.

| Method | Path | Protection / purpose |
|---|---|---|
| GET/POST | `/media-assets` | paginated tenant search / Admin or Backoffice private upload |
| GET/PATCH | `/media-assets/{id}` | detail, versions, rights, variants, relations, audit / optimistic update |
| POST | `/media-assets/{id}/versions` | immutable new version with idempotency |
| GET | `/media-assets/{id}/preview` | authenticated inline preview with optional Range |
| GET | `/media-assets/{id}/download` | authorized audited original download |
| POST | `/media-categories`, `/media-tags` | Admin taxonomy maintenance |
| POST | `/media-assets/{id}/relations`, `/variants` | cycle-safe relation / variant registration |
| PUT/POST | `/media-assets/{id}/rights`, `/rights/review` | rights record and reasoned review |
| POST | `/media-assets/{id}/approval-requests`, `/media-approvals/{id}/resolve` | version-bound human approval |
| POST | `/media-assets/{id}/archive`, `/deletion-requests` | retention lifecycle |
| POST | `/media-deletion-requests/{id}/approve` | Admin-only physical purge gate |
| GET/POST | `/media-collections` | internal collections |
| POST | `/media-collections/{id}/items`, `/order` | tenant-safe membership and order history |

The list is limited to 100 rows per page and supports stable ordering and filters. Readers receive
only `READY` media. The API never returns MinIO credentials, bucket policies, direct object URLs or
secret values. Preview and download responses use detected MIME rather than a client claim.
