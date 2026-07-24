# Hauptblock 6 completion report

## Scope

Hauptblock 6 implements the standalone FUXX MEDIA media-object, asset-lifecycle and versioned-library
core. It contains no external business-system, publishing, email, public-media or external
transcoding integration.

## Implemented

- Additive Alembic media schema with private binary references, immutable versions, separated states,
  taxonomy, metadata, rights, approvals, variants, relations, collections, deletion requests and tasks.
- Signature-based bounded upload validation and local deterministic metadata extraction for the
  supported image, PDF, audio and video formats.
- Authenticated tenant-scoped application/API layer with CSRF, roles, revision checks, idempotency,
  audit, deduplication, private previews/downloads and Range responses.
- Persistent `SKIP LOCKED` media worker with stale-claim recovery, retry/dead letter, integrity
  verification, preview registration, rights expiry and worker-only guarded purge.
- German internal media workspace for upload, search, metadata, versions, rights, review, variants,
  relations, collections, archive/deletion and audit/history.

## Security posture

MinIO objects remain private and content-addressed per tenant. Filenames and client MIME claims do not
establish trust. SVG/HTML and unknown signatures are rejected. Human approvals are version-bound and
self-approval is blocked. No external effect, public link, real provider, callback, email or production
deployment is enabled.

## Acceptance evidence

The local acceptance run on 23 July 2026 completed against the isolated Block 6 test tenant and
resources:

- Docker Desktop `4.82.0` / Engine `29.6.1`; PostgreSQL, MinIO, backend, worker and frontend healthy;
  the migration service exited with status `0`. The persistent PostgreSQL and MinIO volumes were
  preserved.
- Alembic upgraded an empty isolated database to the single head `d7e8f9a0b1c2`, a repeated
  `upgrade head` succeeded, and `alembic check` reported no pending schema operations.
- The complete backend suite passed with `98 passed`; Ruff and strict Mypy passed.
- Frontend lint, typecheck and the production build passed. The final image runs Next.js `16.2.11`.
- `npm audit --omit=dev` reported `0` vulnerabilities after the bounded Next.js, PostCSS and Sharp
  security updates.
- Architecture guard, secret guard, Compose configuration validation, Python sdist and wheel builds
  passed.
- HTTP/security checks proved health, readiness, version and frontend responses, anonymous rejection,
  CSRF and role enforcement, private MinIO access, authenticated download and Range responses, logout
  and revoked-session rejection.
- The 41-step browser acceptance covered upload/signature validation, deterministic metadata,
  preview, version immutability, version-bound rights/content approvals, self-approval prevention,
  variants, cycle-safe relations, collections, search/filter/sort/pagination, private downloads,
  deduplication, archive/deletion safeguards and logout. No browser console error was observed.
- PostgreSQL and MinIO reconciliation proved six immutable versions backed by five content-addressed
  objects, no orphaned versions, no unreferenced files, successful worker tasks, complete audit
  history and no duplicate binary effect.

All isolated acceptance users, tenant rows, database, bucket/prefix, fixtures and downloaded files
were removed after the persistent proof. The immutable-audit trigger was immediately restored and
verified as enabled. Existing application data, buckets and named volumes were not reset or deleted.

No production deployment, external provider, callback, email, public bucket or external effect was
used. GitHub CI evidence is recorded on the Block 6 pull request and is required before merge.
