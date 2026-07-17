# Data model

Migration `32df0ee0c2a1` extends the Phase 0 kernel without replacing it.

## Identity and tenancy

- `Tenant`: tenant identity and active state.
- `User`: tenant-bound normalized email, Argon2id hash, active state.
- `UserRole`: many-to-many role assignment.
- `AuthSession`: hashed session and CSRF secrets, expiry, last activity and revocation.

`Channel`, `ContentJob`, and `AuditEvent` now carry tenant IDs. The migration creates a fixed legacy tenant and safely backfills existing Phase 0 records before adding non-null constraints.

## Intake persistence

- `IdempotencyRecord`: unique tenant/scope/key, request digest and completed response.
- `StoredFile`: tenant-scoped SHA-256 identity, verified MIME, byte size and private MinIO key.
- `JobAttachment`: job-to-file reference and display-only original filename.
- `ContentJob`: the created business process in initial `DRAFT` state.
- `JobTask`: bounded `INTAKE_ACCEPTED` queue work.
- `AuditEvent`: append-only intake, session and download evidence.

Unique constraints prevent duplicate tenant/email, tenant/channel slug, tenant/file hash, object key and job/file attachment. Money remains integer cents and all timestamps are timezone-aware UTC.

Audit mutation remains blocked both by SQLAlchemy listeners and a PostgreSQL update/delete trigger.
