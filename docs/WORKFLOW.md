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
