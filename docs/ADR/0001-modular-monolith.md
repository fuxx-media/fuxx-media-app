# ADR 0001: Modular monolith

- Status: Accepted
- Date: 2026-07-16

## Context

Phase 0 needs a backend API, a background worker, PostgreSQL persistence and queueing, object storage, provider boundaries, and an internal frontend. The product behavior is not yet mature enough to justify distributed-service complexity.

## Decision

Use one Python application package with domain, application, infrastructure, API, and worker modules. Run the FastAPI backend and Python worker as separate processes from the same build. Use PostgreSQL as the only system of record and future queue, MinIO for artifact bytes, and Next.js for the internal frontend.

## Consequences

- Domain and application behavior remain in one repository and one deployable codebase.
- Backend and worker can scale independently at the process level without becoming separate services.
- Transactions remain local to PostgreSQL and application services.
- Redis, Kafka, RabbitMQ, Temporal, Supabase, GraphQL, Elasticsearch, and microservice infrastructure are unnecessary and prohibited in Phase 0.
- A future architecture change requires measured evidence and a new ADR.

