# Data model

## Phase 0.1 status

Business tables are intentionally not implemented in Phase 0.1. Alembic is operational and the baseline migration establishes only migration infrastructure.

## Planned Phase 0 entities

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

All entities will use UUID primary keys and UTC timestamps. Monetary fields will be integer cents. Workflow and task states will be typed enums. `ContentJob` will carry an integer version used for optimistic concurrency control.

PostgreSQL is the sole system of record. MinIO stores artifact bytes; PostgreSQL stores artifact identity, ownership, metadata, checksums, and lifecycle state.

