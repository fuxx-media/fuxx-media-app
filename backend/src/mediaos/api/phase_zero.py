"""Phase 0 channel, job, workflow, cost, timeline, and audit API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.api.auth import require_actor, require_review_actor, require_write_actor
from mediaos.api.schemas import (
    AuditResponse,
    ChannelCreate,
    ChannelResponse,
    ContentJobCreate,
    ContentJobResponse,
    CostResponse,
    TransitionRequest,
    TransitionResponse,
)
from mediaos.application.errors import JobNotFoundError
from mediaos.application.idempotency_service import (
    acquire_idempotency,
    canonical_request_hash,
    record_idempotency,
)
from mediaos.application.workflow_transition_service import WorkflowTransitionService
from mediaos.database import get_session
from mediaos.domain.actor import Actor
from mediaos.domain.models import AuditEvent, CostEntry, WorkflowTransition
from mediaos.infrastructure.repositories import ChannelRepository, ContentJobRepository

router = APIRouter(prefix="/api/v1", tags=["phase-zero"])
Session = Annotated[AsyncSession, Depends(get_session)]
AuthenticatedActor = Annotated[Actor, Depends(require_actor)]
WriteActor = Annotated[Actor, Depends(require_write_actor)]
ReviewActor = Annotated[Actor, Depends(require_review_actor)]


@router.post("/channels", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED)
async def create_channel(
    body: ChannelCreate,
    session: Session,
    actor: WriteActor,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> ChannelResponse:
    tenant_id = _tenant(actor)
    try:
        async with session.begin():
            request_hash = canonical_request_hash(body.model_dump(mode="json"))
            replay = await acquire_idempotency(
                session,
                tenant_id=tenant_id,
                scope="CREATE_CHANNEL",
                key=idempotency_key,
                request_hash=request_hash,
            )
            if replay is not None:
                return ChannelResponse.model_validate(replay.response_body)
            channel = await ChannelRepository(session).create(
                tenant_id=tenant_id, name=body.name, slug=body.slug
            )
            session.add(
                AuditEvent(
                    tenant_id=tenant_id,
                    actor_id=actor.id,
                    actor_type=actor.type,
                    event_type="CHANNEL_CREATED",
                    payload={"channel_id": str(channel.id), "slug": channel.slug},
                )
            )
            response = ChannelResponse.model_validate(channel)
            record_idempotency(
                session,
                tenant_id=tenant_id,
                scope="CREATE_CHANNEL",
                key=idempotency_key,
                request_hash=request_hash,
                response_status=201,
                response_body=response.model_dump(mode="json"),
            )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Channel slug already exists") from exc
    return response


@router.post("/jobs", response_model=ContentJobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    body: ContentJobCreate,
    session: Session,
    actor: WriteActor,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> ContentJobResponse:
    tenant_id = _tenant(actor)
    async with session.begin():
        request_hash = canonical_request_hash(body.model_dump(mode="json"))
        replay = await acquire_idempotency(
            session,
            tenant_id=tenant_id,
            scope="CREATE_JOB",
            key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            return ContentJobResponse.model_validate(replay.response_body)
        if await ChannelRepository(session).get(body.channel_id, tenant_id=tenant_id) is None:
            raise HTTPException(status_code=404, detail="Channel was not found")
        job = await ContentJobRepository(session).create(
            tenant_id=tenant_id,
            channel_id=body.channel_id,
            title=body.title,
            budget_limit_cents=body.budget_limit_cents,
        )
        session.add(
            AuditEvent(
                tenant_id=tenant_id,
                job_id=job.id,
                actor_id=actor.id,
                actor_type=actor.type,
                event_type="CONTENT_JOB_CREATED",
                payload={"channel_id": str(job.channel_id), "version": job.version},
            )
        )
        response = ContentJobResponse.model_validate(job)
        record_idempotency(
            session,
            tenant_id=tenant_id,
            scope="CREATE_JOB",
            key=idempotency_key,
            request_hash=request_hash,
            response_status=201,
            response_body=response.model_dump(mode="json"),
        )
    return response


@router.post("/jobs/{job_id}/transitions", response_model=ContentJobResponse)
async def transition_job(
    job_id: UUID,
    body: TransitionRequest,
    session: Session,
    actor: ReviewActor,
) -> ContentJobResponse:
    job = await WorkflowTransitionService(session).transition_job(
        job_id=job_id,
        target_state=body.target_state,
        actor=actor,
        reason=body.reason,
        expected_version=body.expected_version,
    )
    return ContentJobResponse.model_validate(job)


@router.get("/jobs/{job_id}/timeline", response_model=list[TransitionResponse])
async def get_timeline(
    job_id: UUID, session: Session, actor: AuthenticatedActor
) -> list[TransitionResponse]:
    await _require_job(session, job_id, _tenant(actor))
    result = await session.scalars(
        select(WorkflowTransition)
        .where(WorkflowTransition.job_id == job_id)
        .order_by(WorkflowTransition.created_at)
    )
    return [TransitionResponse.model_validate(item) for item in result]


@router.get("/jobs/{job_id}/costs", response_model=list[CostResponse])
async def get_costs(
    job_id: UUID, session: Session, actor: AuthenticatedActor
) -> list[CostResponse]:
    await _require_job(session, job_id, _tenant(actor))
    result = await session.scalars(
        select(CostEntry).where(CostEntry.job_id == job_id).order_by(CostEntry.created_at)
    )
    return [CostResponse.model_validate(item) for item in result]


@router.get("/jobs/{job_id}/audit", response_model=list[AuditResponse])
async def get_audit(
    job_id: UUID, session: Session, actor: AuthenticatedActor
) -> list[AuditResponse]:
    await _require_job(session, job_id, _tenant(actor))
    result = await session.scalars(
        select(AuditEvent).where(AuditEvent.job_id == job_id).order_by(AuditEvent.created_at)
    )
    return [AuditResponse.model_validate(item) for item in result]


async def _require_job(session: AsyncSession, job_id: UUID, tenant_id: UUID) -> None:
    if await ContentJobRepository(session).get(job_id, tenant_id=tenant_id) is None:
        raise JobNotFoundError("Content job was not found", details={"job_id": str(job_id)})


def _tenant(actor: Actor) -> UUID:
    if actor.tenant_id is None:
        raise HTTPException(status_code=403, detail="Authenticated actor has no tenant")
    return actor.tenant_id
