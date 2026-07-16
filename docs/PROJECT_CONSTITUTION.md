# MediaOS project constitution

## Product objective

MediaOS will eventually turn approved information sources into complete video content through a controlled, auditable, human-approved process. Phase 0 provides the technical foundation and auditable workflow kernel for that future workflow.

## Current binding scope

Phase 0 includes repository structure, Docker Compose infrastructure, the core data model, the atomic workflow transition service, PostgreSQL task claiming, internal APIs, documentation, tests, CI, and architecture enforcement. It does not include real providers, research execution, voice/image/video generation, real publishing, YouTube, customer communication, multilingual behavior, or multi-tenancy.

## Architectural authority

- PostgreSQL is the only system of record.
- The application is a modular monolith.
- Backend and worker share one Python application package and run as separate processes.
- MinIO is object storage, not a second business-data database.
- PostgreSQL will be the only job queue.
- Provider integrations must sit behind internal interfaces.
- Workflow state will change only through the central transition service.

## Data and security invariants

- UUID primary keys, UTC timestamps, typed enums, and integer-cent money values are mandatory and implemented.
- Audit events are immutable.
- Secrets are supplied only through environment variables and never returned or logged.
- Write APIs require a validated Phase 0 actor identity; production authentication integration remains a later boundary decision.
- Production-affecting flags remain disabled unless explicitly approved.
- No real external provider or customer communication is permitted in Phase 0.

## Change governance

Every change must state its Phase 0 objective, tests, cost, introduced complexity, and explicit non-goals. Architecture changes require an ADR. The CI and architecture checker enforce the machine-checkable subset; reviewers remain responsible for business and scope judgments.
