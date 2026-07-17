# ADR 0003: Persistent session and intake boundary

Status: accepted

MediaOS uses opaque server-side sessions rather than browser bearer tokens. Session and CSRF secrets are random; only digests are persisted. Tenant and roles are loaded from PostgreSQL on every protected request.

File bytes are private in MinIO while PostgreSQL owns identity, tenant, digest, attachment, audit and queue state. Cross-system atomicity is implemented as a PostgreSQL transaction plus compensating object deletion. Idempotency uses PostgreSQL advisory transaction locks and durable response records.

This keeps authentication provider-independent, prevents Local Storage token exposure and preserves PostgreSQL as the sole business system of record.
