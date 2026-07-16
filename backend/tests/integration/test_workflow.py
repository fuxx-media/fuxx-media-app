"""Atomic workflow transition integration tests."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.application.errors import (
    BudgetLimitExceededError,
    InvalidStateTransitionError,
    VersionConflictError,
)
from mediaos.application.workflow_transition_service import (
    ALLOWED_TRANSITIONS,
    WorkflowTransitionService,
)
from mediaos.domain.actor import Actor
from mediaos.domain.enums import ActorType, ApprovalStatus, ArtifactKind, WorkflowState
from mediaos.domain.models import (
    ApprovalRequest,
    Artifact,
    AuditEvent,
    Channel,
    ContentJob,
    CostEntry,
    WorkflowTransition,
)

pytestmark = pytest.mark.integration
ACTOR = Actor(id=uuid4(), type=ActorType.USER)
ALL_ALLOWED_EDGES = [
    (source, target) for source, targets in ALLOWED_TRANSITIONS.items() for target in targets
]


async def _job(session: AsyncSession, state: WorkflowState, budget: int = 1_000) -> ContentJob:
    async with session.begin():
        channel = Channel(name="Workflow", slug=f"workflow-{uuid4().hex}")
        session.add(channel)
        await session.flush()
        job = ContentJob(
            channel_id=channel.id,
            title="Transition proof",
            current_state=state,
            budget_limit_cents=budget,
        )
        session.add(job)
        await session.flush()
        if WorkflowState.AWAITING_APPROVAL in ALLOWED_TRANSITIONS[state]:
            session.add(
                Artifact(
                    job_id=job.id,
                    kind=ArtifactKind.VIDEO,
                    bucket="workflow",
                    object_key=f"{uuid4()}.mp4",
                    sha256="b" * 64,
                    size_bytes=1,
                )
            )
        if WorkflowState.APPROVED in ALLOWED_TRANSITIONS[state]:
            session.add(
                ApprovalRequest(
                    job_id=job.id,
                    status=ApprovalStatus.APPROVED,
                    requested_by=ACTOR.id,
                    resolved_by=ACTOR.id,
                )
            )
    return job


@pytest.mark.parametrize(("source", "target"), ALL_ALLOWED_EDGES)
async def test_every_allowed_transition_is_recorded_atomically(
    integration_session: AsyncSession, source: WorkflowState, target: WorkflowState
) -> None:
    job = await _job(integration_session, source)
    transitioned = await WorkflowTransitionService(integration_session).transition_job(
        job.id, target, ACTOR, "matrix proof", 1
    )
    assert transitioned.current_state == target
    assert transitioned.version == 2
    transition_count = await integration_session.scalar(
        select(func.count(WorkflowTransition.id)).where(WorkflowTransition.job_id == job.id)
    )
    audit_count = await integration_session.scalar(
        select(func.count(AuditEvent.id)).where(AuditEvent.job_id == job.id)
    )
    assert transition_count == 1
    assert audit_count == 1


async def test_invalid_transition_rolls_back(integration_session: AsyncSession) -> None:
    job = await _job(integration_session, WorkflowState.DRAFT)
    with pytest.raises(InvalidStateTransitionError):
        await WorkflowTransitionService(integration_session).transition_job(
            job.id, WorkflowState.PUBLISHED, ACTOR, None, 1
        )
    await integration_session.refresh(job)
    assert job.current_state == WorkflowState.DRAFT
    assert job.version == 1


async def test_version_conflict_rolls_back(integration_session: AsyncSession) -> None:
    job = await _job(integration_session, WorkflowState.DRAFT)
    with pytest.raises(VersionConflictError):
        await WorkflowTransitionService(integration_session).transition_job(
            job.id, WorkflowState.TOPIC_APPROVED, ACTOR, None, 99
        )
    await integration_session.refresh(job)
    assert job.version == 1


async def test_budget_limit_rolls_back_all_records(integration_session: AsyncSession) -> None:
    job = await _job(integration_session, WorkflowState.DRAFT, budget=10)
    job_id = job.id
    async with integration_session.begin():
        integration_session.add(CostEntry(job_id=job.id, category="test", amount_cents=11))
    with pytest.raises(BudgetLimitExceededError):
        await WorkflowTransitionService(integration_session).transition_job(
            job.id, WorkflowState.TOPIC_APPROVED, ACTOR, None, 1
        )
    transition_count = await integration_session.scalar(
        select(func.count(WorkflowTransition.id)).where(WorkflowTransition.job_id == job_id)
    )
    assert transition_count == 0
