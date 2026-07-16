# Data model

## Phase 0 status

Migration `086e30120b92` implements the complete Phase 0 relational kernel in PostgreSQL.

## Implemented entities

- `Channel`
- `ContentJob`
- `WorkflowTransition`
- `AuditEvent`
- `ProviderConfiguration`
- `ProviderCall`
- `CostEntry`
- `ApprovalRequest`
- `JobTask`
- `Artifact`

All entities use UUID primary keys and UTC timestamps. Monetary fields are database integers constrained to non-negative cent values. Workflow, approval, provider-call, artifact, and task states are typed enums. `ContentJob.version` starts at one and is checked under a row lock for optimistic concurrency control.

Foreign keys use explicit deletion behavior. Queue claiming is indexed by status, availability, and creation time. Audit events are append-only in both SQLAlchemy and PostgreSQL through an update/delete rejection trigger.

PostgreSQL is the sole system of record. MinIO stores artifact bytes; PostgreSQL stores artifact identity, ownership, metadata, checksums, and lifecycle state.
