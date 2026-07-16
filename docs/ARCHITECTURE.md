# Architecture

## System shape

```text
Next.js frontend
        |
        v
FastAPI backend
        |
        +-- PostgreSQL 16 (system of record and future queue)
        +-- MinIO (artifact object storage)
        |
        +-- shared Python application code
                    |
                    v
              Python worker
```

The deployment contains multiple processes, not microservices. Backend and worker are built from the same Python package and share domain, application, and infrastructure modules.

## Module boundaries

- `domain`: entities, value objects, and workflow enums; no framework or provider code.
- `application`: use cases, transaction boundaries, transition service, and provider protocols.
- `infrastructure`: SQLAlchemy, PostgreSQL queue, MinIO, and adapter implementations.
- `api`: FastAPI routers, schemas, authentication, and error mapping.
- `worker`: task-claim loop and application-service dispatch.

Phase 0.1 creates these boundaries but deliberately leaves later business behavior unimplemented.

## Runtime foundation

- PostgreSQL and MinIO have persistent named volumes.
- Alembic runs as a one-shot service before backend and worker.
- Backend readiness checks PostgreSQL and MinIO.
- Worker performs a database heartbeat only in Phase 0.1. It does not claim queue support.
- Frontend is a minimal internal status surface and uses the versioned backend base URL.

## Transactions and state

The future `WorkflowTransitionService` owns the atomic transaction for state changes, optimistic version checks, transition records, audit events, prerequisites, and cost-limit checks. Repositories, providers, API handlers, and workers are forbidden from directly mutating `current_state`.

## Security boundaries

Runtime credentials enter through process environment variables. No populated environment file is required or committed. Containers run as non-root application users where supported. Public Phase 0.1 endpoints are read-only health metadata; future write routes require authentication and authorization.

## Allowed repository extensions

The target tree is extended only by explicitly required governance files, lock files, container build files, test/package markers, framework configuration, and reports. `scripts/check_architecture.py` contains the authoritative machine-readable allowlist.

