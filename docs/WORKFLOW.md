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

## Phase 0.1 status

The workflow is documented but not implemented. This avoids introducing business behavior before the data model work package. The architecture checker already reserves the transition-service path and rejects direct Python assignment to `current_state` elsewhere.

