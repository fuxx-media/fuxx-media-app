# Phase 2 completion report

Phase 2 implements internal case worklists, assignment and expiring claims, classification,
priority, wiedervorlage, immutable notes, checklists, evidence, revision-bound four-eyes approval,
controlled completion and durable queue continuation without external effect.

## Security invariants

- Session, CSRF, role and tenant checks from Phase 1 remain mandatory.
- Every material write requires the current case revision and an owned active claim.
- Self approval, stale approval, incomplete checklists and foreign-tenant access are rejected.
- Material changes invalidate prior approvals and append a revision plus audit evidence.
- Notes, revisions and audit rows cannot be silently updated or deleted.
- No external provider, mail or publishing path is enabled.

## Acceptance evidence

The complete suite migrates an empty PostgreSQL database to `a4f1c2d3e4f5`, repeats the migration,
and passes 74 backend tests. Ruff, Mypy strict, frontend lint/typecheck/production build,
architecture guard, package build, npm audit, Compose health and browser workflow are required
before the Phase 2 PR is marked ready.

The browser acceptance used separate local Backoffice and Reviewer users. It exercised claim,
classification, priority, wiedervorlage, checklist prerequisite rejection, note, evidence,
self-approval rejection, reviewer rejection, correction, resubmission, approval, material-change
invalidation, renewed approval and internal completion. The detail view showed the immutable
revision/audit chain and invalidated historical approval.
