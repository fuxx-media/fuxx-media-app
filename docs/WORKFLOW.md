# Workflow

## Required states

```text
DRAFT
TOPIC_APPROVED
RESEARCHING
RESEARCH_REVIEW
SCRIPTING
SCRIPT_REVIEW
SCENE_PLANNING
MEDIA_PRODUCTION
VOICE_PRODUCTION
RENDERING
QUALITY_REVIEW
AWAITING_APPROVAL
APPROVED
PUBLISHING
PUBLISHED
REJECTED
FAILED
```

## Invariant

`current_state` may never be changed directly by an API handler, repository, provider, or worker. Only `WorkflowTransitionService.transition_job(...)` may perform a state change, and it must atomically validate the expected version, transition, prerequisites, and cost limit before persisting the job, transition record, and audit event.

## Implemented transition matrix

The authoritative matrix is `ALLOWED_TRANSITIONS` in `workflow_transition_service.py`. It follows the forward production sequence, permits review loops back to the relevant authoring stage, permits rejection/failure where defined, and permits rejected or failed jobs to return only to `DRAFT`.

Transitions to `AWAITING_APPROVAL` require a video artifact. Transitions to `APPROVED` require an approved approval request. Every transition checks the current summed cost against `budget_limit_cents`, increments the optimistic version, and writes both `WorkflowTransition` and `AuditEvent` in the same transaction.

Stable errors are `VERSION_CONFLICT`, `INVALID_STATE_TRANSITION`, `BUDGET_LIMIT_EXCEEDED`, `STATE_PREREQUISITE_FAILED`, and `JOB_NOT_FOUND`.

## Provider execution workflow

Provider execution does not mutate `current_state`. It has an independent state machine:

```text
VALIDATED / DRY_RUN_SUCCEEDED / DRY_RUN_FAILED
QUEUED -> RUNNING -> SUCCEEDED
                  -> RETRY -> RUNNING
                  -> AMBIGUOUS
                  -> DEAD_LETTER -> QUEUED (reasoned Admin resume)
QUEUED -> INVALIDATED (new case revision)
DEAD_LETTER/AMBIGUOUS -> DISCARDED (reasoned Admin decision)
```

Outbox and attempt states remain separate. Neither a business approval nor a queued outbox row is
an externally confirmed result. Phase 3 has no productive adapter and therefore all results retain
`external_effect=false`.
