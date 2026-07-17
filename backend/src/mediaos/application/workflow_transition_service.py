"""The sole authority for workflow state changes."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.application.errors import (
    BudgetLimitExceededError,
    InvalidStateTransitionError,
    JobNotFoundError,
    StatePrerequisiteError,
    VersionConflictError,
)
from mediaos.domain.actor import Actor
from mediaos.domain.enums import ApprovalStatus, ArtifactKind, WorkflowState
from mediaos.domain.models import (
    ApprovalRequest,
    Artifact,
    AuditEvent,
    ContentJob,
    CostEntry,
    WorkflowTransition,
)
from mediaos.infrastructure.repositories import ContentJobRepository

ALLOWED_TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.DRAFT: frozenset(
        {WorkflowState.TOPIC_APPROVED, WorkflowState.REJECTED, WorkflowState.FAILED}
    ),
    WorkflowState.TOPIC_APPROVED: frozenset(
        {WorkflowState.RESEARCHING, WorkflowState.REJECTED, WorkflowState.FAILED}
    ),
    WorkflowState.RESEARCHING: frozenset({WorkflowState.RESEARCH_REVIEW, WorkflowState.FAILED}),
    WorkflowState.RESEARCH_REVIEW: frozenset(
        {
            WorkflowState.RESEARCHING,
            WorkflowState.SCRIPTING,
            WorkflowState.REJECTED,
            WorkflowState.FAILED,
        }
    ),
    WorkflowState.SCRIPTING: frozenset({WorkflowState.SCRIPT_REVIEW, WorkflowState.FAILED}),
    WorkflowState.SCRIPT_REVIEW: frozenset(
        {
            WorkflowState.SCRIPTING,
            WorkflowState.SCENE_PLANNING,
            WorkflowState.REJECTED,
            WorkflowState.FAILED,
        }
    ),
    WorkflowState.SCENE_PLANNING: frozenset(
        {WorkflowState.MEDIA_PRODUCTION, WorkflowState.REJECTED, WorkflowState.FAILED}
    ),
    WorkflowState.MEDIA_PRODUCTION: frozenset(
        {WorkflowState.VOICE_PRODUCTION, WorkflowState.FAILED}
    ),
    WorkflowState.VOICE_PRODUCTION: frozenset({WorkflowState.RENDERING, WorkflowState.FAILED}),
    WorkflowState.RENDERING: frozenset({WorkflowState.QUALITY_REVIEW, WorkflowState.FAILED}),
    WorkflowState.QUALITY_REVIEW: frozenset(
        {WorkflowState.SCENE_PLANNING, WorkflowState.AWAITING_APPROVAL, WorkflowState.FAILED}
    ),
    WorkflowState.AWAITING_APPROVAL: frozenset(
        {WorkflowState.APPROVED, WorkflowState.REJECTED, WorkflowState.FAILED}
    ),
    WorkflowState.APPROVED: frozenset(
        {WorkflowState.PUBLISHING, WorkflowState.REJECTED, WorkflowState.FAILED}
    ),
    WorkflowState.PUBLISHING: frozenset({WorkflowState.PUBLISHED, WorkflowState.FAILED}),
    WorkflowState.PUBLISHED: frozenset(),
    WorkflowState.REJECTED: frozenset({WorkflowState.DRAFT}),
    WorkflowState.FAILED: frozenset({WorkflowState.DRAFT}),
}


class WorkflowTransitionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.jobs = ContentJobRepository(session)

    async def transition_job(
        self,
        job_id: UUID,
        target_state: WorkflowState,
        actor: Actor,
        reason: str | None,
        expected_version: int,
    ) -> ContentJob:
        async with self.session.begin():
            job = await self.jobs.get_for_update(job_id, tenant_id=actor.tenant_id)
            if job is None:
                raise JobNotFoundError("Content job was not found", details={"job_id": str(job_id)})
            if job.version != expected_version:
                raise VersionConflictError(
                    "Content job version does not match",
                    details={"expected": expected_version, "actual": job.version},
                )
            if target_state not in ALLOWED_TRANSITIONS[job.current_state]:
                raise InvalidStateTransitionError(
                    "Workflow transition is not allowed",
                    details={"from": job.current_state.value, "to": target_state.value},
                )

            await self._verify_prerequisites(job, target_state)
            spent_cents = await self._current_cost(job.id)
            if spent_cents > job.budget_limit_cents:
                raise BudgetLimitExceededError(
                    "Content job budget limit is exceeded",
                    details={"spent_cents": spent_cents, "limit_cents": job.budget_limit_cents},
                )

            previous_state = job.current_state
            job.current_state = target_state
            job.version += 1
            job.spent_cents = spent_cents
            self.session.add(
                WorkflowTransition(
                    job_id=job.id,
                    from_state=previous_state,
                    to_state=target_state,
                    actor_id=actor.id,
                    actor_type=actor.type,
                    reason=reason,
                    job_version=job.version,
                )
            )
            self.session.add(
                AuditEvent(
                    tenant_id=job.tenant_id,
                    job_id=job.id,
                    actor_id=actor.id,
                    actor_type=actor.type,
                    event_type="WORKFLOW_TRANSITION",
                    payload={
                        "from_state": previous_state.value,
                        "to_state": target_state.value,
                        "version": job.version,
                        "reason": reason,
                    },
                )
            )
        await self.session.refresh(job)
        return job

    async def _current_cost(self, job_id: UUID) -> int:
        result = await self.session.execute(
            select(func.coalesce(func.sum(CostEntry.amount_cents), 0)).where(
                CostEntry.job_id == job_id
            )
        )
        return int(result.scalar_one())

    async def _verify_prerequisites(self, job: ContentJob, target_state: WorkflowState) -> None:
        if target_state == WorkflowState.AWAITING_APPROVAL:
            artifact_count = await self.session.scalar(
                select(func.count(Artifact.id)).where(
                    Artifact.job_id == job.id,
                    Artifact.kind == ArtifactKind.VIDEO,
                )
            )
            if not artifact_count:
                raise StatePrerequisiteError("A video artifact is required before approval")
        if target_state == WorkflowState.APPROVED:
            approval_count = await self.session.scalar(
                select(func.count(ApprovalRequest.id)).where(
                    ApprovalRequest.job_id == job.id,
                    ApprovalRequest.status == ApprovalStatus.APPROVED,
                )
            )
            if not approval_count:
                raise StatePrerequisiteError("An approved approval request is required")
