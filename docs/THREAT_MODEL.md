# Threat model

## Protected assets

User credentials, session secrets, tenant business processes, uploaded files, audit history, queue state and object-storage credentials.

## Material threats and controls

- Credential theft: Argon2id hashes; plaintext passwords are never persisted or logged.
- Session theft: random opaque tokens, database digests, HttpOnly and SameSite=Strict cookies, expiry and revocation.
- CSRF: server-bound secret plus cookie/header equality on mutating authenticated requests.
- Tenant data exposure: tenant is server-derived and included in all protected resource queries.
- Replay and concurrent duplicates: advisory transaction locks and persisted request hashes/responses.
- Malicious upload: bounded read, content signature detection, declared/detected MIME equality, SHA-256 and private object storage.
- Filename deception: filenames are never used for MIME or trust decisions and are stored only as sanitized display metadata.
- Public file exposure: no public bucket policy or direct object URL; downloads pass session and tenant checks and are audited.
- Queue duplication: `SKIP LOCKED`, attempt counters, retry scheduling and persistent terminal failure.
- Audit tampering: append-only ORM listeners and database trigger.
- Secret leakage: environment-only credentials and architecture secret scanning.
- Lost updates: expiring database claims plus `expected_version` optimistic locking.
- Self approval: approval requests reject their requester and the last material editor; workers
  cannot act as human reviewers.
- Stale approval: every request binds to one revision and material changes persist an invalidation
  timestamp before a new request can be created.
- Internal-content injection: lengths are bounded and React renders notes/evidence as text; no
  stored HTML or automatic external URL fetching exists.
- Direct external side effects: domain/case services have no adapter dependency; only an immutable
  order and transactional outbox can reach the provider worker.
- Provider replay/double effect: tenant/provider/operation/case/revision fingerprints, caller keys,
  row locking and persisted responses collapse identical requests.
- Provider ambiguity: unknown status remains `AMBIGUOUS`, never success, and requires a signed
  callback or reasoned admin intervention.
- Callback forgery/replay: HMAC-SHA256, timestamp tolerance, event ID uniqueness, correlation and
  tenant/provider matching precede every status change.
- Secret disclosure: configuration stores an environment-variable reference only; recursive masking
  covers prepared payloads, normalized responses, callbacks and API output.

## Residual risks

Local MinIO uses an administrative credential shared by backend and worker. A later production deployment should provision a least-privilege application service account. Session cookies require `MEDIAOS_COOKIE_SECURE=true` behind production HTTPS. Rate limiting and account lockout are not part of the local Phase 1 foundation and must be added before public internet exposure.
The in-memory simulation adapter status cache is diagnostic only; PostgreSQL remains authoritative.
Before any real provider is added, provider-specific egress allowlists, credential rotation and
external contract certification remain mandatory.
