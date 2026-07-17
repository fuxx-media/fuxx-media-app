# Phase 3 completion report

Phase 3 adds a provider-independent, revision-bound execution foundation. Domain services do not
call providers directly. A business approval and a separate technical approval create an immutable
execution order and an outbox event in one transaction; only the worker crosses the adapter
boundary. The phase contains no real provider adapter and cannot perform a productive external
write.

## Security invariants

- The only enabled provider type is the local simulation provider.
- Global integration and dry-run are enabled for internal use; productive execution and callback
  intake are disabled by default and at acceptance completion.
- Provider configurations store environment-variable secret references, never secret values.
- Dry-runs use the same validation and preparation path, persist masked evidence and always record
  `external_effect=false`.
- Execution idempotency binds tenant, provider, operation, case, approved revision and prepared
  request. Outbox claiming uses PostgreSQL row locking with `SKIP LOCKED`.
- Temporary, timeout and rate-limit failures are retried with persisted backoff. Permanent failures
  go directly to dead letter. Ambiguous responses never become success without a separately
  signed and verified callback.
- Callbacks require an HMAC signature, a current timestamp, a unique event ID and a known
  correlation ID. Raw and normalized payloads are size-limited and secret-masked.
- Discard is terminal, requires an Admin reason and is accepted only from `DEAD_LETTER` or
  `AMBIGUOUS`; repeated discard cannot append duplicate terminal audit evidence.

## Acceptance evidence

- The final Compose images started with PostgreSQL, MinIO, backend, worker and frontend healthy;
  the migration container exited `0`. Existing PostgreSQL and MinIO volumes remained mounted.
- The live database and an isolated empty database reached the single Alembic head
  `b5e6f7a8c9d0`; repeating `upgrade head` succeeded.
- The final backend image passed 91 tests. Ruff, Mypy strict across 42 source files, frontend lint,
  TypeScript, production build, architecture/secret guard, Compose validation, npm audit with zero
  vulnerabilities, Python sdist and wheel all passed.
- Browser acceptance covered provider configuration, masked secret references, dry-run, technical
  approval, success, temporary error and retry, permanent error, timeout, rate limit, dead letter,
  manual resume, reasoned discard, duplicate execution, ambiguous status, signed callback evidence,
  disabled productive execution and logout. Browser console errors and warnings: none.
- The signed localhost callback returned `200`; replay returned `409`; invalid signature and expired
  timestamp returned `422`. Both callback gates were restored to `false` afterward.
- PostgreSQL retained seven execution orders with no missing or orphaned outbox rows. The maximum
  duplicate count per request fingerprint was one, every order had `external_effect=false`, result
  artifact hashes were valid SHA-256 values, and persisted callback payloads contained no test
  secret value.

## Operational state

- Provider integration: internally enabled.
- Simulation provider: enabled.
- Dry-run: enabled.
- Productive execution: disabled.
- Real providers: absent and disabled.
- Callback intake: disabled.
- Production deployment: not performed.
