# Data model

Migration `32df0ee0c2a1` extends the Phase 0 kernel without replacing it.

## Identity and tenancy

- `Tenant`: tenant identity and active state.
- `User`: tenant-bound normalized email, Argon2id hash, active state.
- `UserRole`: many-to-many role assignment.
- `AuthSession`: hashed session and CSRF secrets, expiry, last activity and revocation.

`Channel`, `ContentJob`, and `AuditEvent` now carry tenant IDs. The migration creates a fixed legacy tenant and safely backfills existing Phase 0 records before adding non-null constraints.

Provider configuration names are unique within a tenant. Global configurations use a separate
partial unique index, so two tenants may use the same human-readable provider name without sharing
configuration or credentials.

## Intake persistence

- `IdempotencyRecord`: unique tenant/scope/key, request digest and completed response.
- `StoredFile`: tenant-scoped SHA-256 identity, verified MIME, byte size and private MinIO key.
- `JobAttachment`: job-to-file reference and display-only original filename.
- `ContentJob`: the created business process in initial `DRAFT` state.
- `JobTask`: bounded `INTAKE_ACCEPTED` queue work.
- `AuditEvent`: append-only intake, session and download evidence.

Unique constraints prevent duplicate tenant/email, tenant/channel slug, tenant/file hash, object key and job/file attachment. Money remains integer cents and all timestamps are timezone-aware UTC.

Audit mutation remains blocked both by SQLAlchemy listeners and a PostgreSQL update/delete trigger.

## Phase 2 processing model

Migration `a4f1c2d3e4f5` adds category, priority, business status, assignment, expiring claim,
wiedervorlage, last material actor and completion reason to `ContentJob`.

- `CaseRevision`: immutable snapshot for each material version.
- `ChecklistItem`: ordered required/optional control with actor and completion timestamp.
- `InternalNote`: append-only internal note bound to the resulting revision.
- `CaseEvidence`: structured evidence or a tenant-checked Phase-1 file reference.
- `ApprovalRequest`: exact `job_revision`, reviewer claim, decision, reason and invalidation time.

Changing classification, checklist, note, evidence, priority, assignment or due date increments the
revision and invalidates all prior active approvals. Approval decisions do not rewrite historical
requests. Queue success, retry and terminal failure remain durable PostgreSQL states.

## Phase 3 provider and execution model

Migration `b5e6f7a8c9d0` adds tenant provider flags, secret references, signature profiles,
provider capabilities and simulation scenarios. `TechnicalApproval` binds one provider capability
to the exact case revision and business approval gate.

`ExecutionOrder` stores the immutable prepared request identity, idempotency fingerprint,
correlation ID, business/technical approvals, dry-run marker and strictly separated execution
status. `ExecutionRevision` and `DryRunResult` are immutable. `OutboxEvent` is created in the same
PostgreSQL transaction as a non-dry execution order. `ExecutionAttempt`, `ProviderResponse`,
`RetryPlan`, `ResultArtifact` and `CallbackReceipt` retain each worker/provider outcome, classified
error, backoff, normalized response, SHA-256 artifact and signed callback receipt. Unique constraints
protect idempotency per tenant/provider/operation/case/revision and callback replay per provider/event.

## Hauptblock 6 media model

Migration `d7e8f9a0b1c2` adds the standalone media aggregate without changing existing case or
provider tables.

- `MediaAsset`: tenant, title/description/type/category, separated lifecycle states, current version,
  owner/editor, confidentiality, retention, archive and deletion hold.
- `MediaFile`: private MinIO bucket/key, tenant-scoped SHA-256 plus size identity, detected MIME and
  signature, storage/verification state, last integrity check and quarantine flag.
- `MediaVersion`: immutable version number, file reference, sanitized original name, claimed and
  detected MIME, media type, size/hash, reason, technical results, version-bound approval and
  supersession link.
- `MediaMetadata`: separated technical, business, custom and system-generated JSON documents.
- `MediaCategory`, `MediaTag`, `MediaAssetTag`: tenant-safe hierarchical taxonomy, synonyms and
  disable-instead-of-delete semantics.
- `MediaVariant`, `MediaRelation`: preview/format records and typed, cycle-safe asset relations.
- `MediaRights`, `MediaApproval`: license facts, proof reference, review reason and version-bound
  human decision. A new version never inherits approval.
- `MediaCollection`, `MediaCollectionItem`, `MediaCollectionHistory`: ordered internal collections
  with immutable change history and no publication effect.
- `MediaDeletionRequest`, `MediaTask`: approval-gated retention/deletion and durable worker claims,
  retry/dead-letter evidence.

`AuditEvent.media_asset_id` binds append-only history directly to an asset. Unique constraints protect
file deduplication, one current version, version numbers, relation identity, collection membership and
worker-task idempotency. The PostgreSQL role enum is additively extended with `READER`; downgrade does
not remove this enum value because PostgreSQL enum value removal is not transaction-safe.
