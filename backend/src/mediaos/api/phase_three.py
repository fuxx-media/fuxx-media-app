"""Phase 3 provider foundation API with no productive external execution."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.api.auth import (
    SessionContext,
    require_admin_actor,
    require_session_context,
    require_write_actor,
)
from mediaos.application.callback_service import CallbackService
from mediaos.application.provider_service import ProviderService
from mediaos.database import get_session
from mediaos.domain.actor import Actor
from mediaos.domain.enums import SimulationScenario

router = APIRouter(prefix="/api/v1", tags=["phase-three"])
Session = Annotated[AsyncSession, Depends(get_session)]


class ProviderConfigurationBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    secret_reference_name: str = Field(min_length=1, max_length=100)
    secret_environment_variable: str = Field(
        min_length=9, max_length=200, pattern=r"^MEDIAOS_[A-Z0-9_]+$"
    )
    signature_profile_name: str = Field(min_length=1, max_length=100)
    capability_operation: str = Field(
        default="SIMULATE_CASE", min_length=1, max_length=100, pattern=r"^[A-Z0-9_]+$"
    )


class TechnicalApprovalBody(BaseModel):
    capability_id: UUID
    job_id: UUID
    reason: str = Field(min_length=1, max_length=2000)


class DryRunBody(BaseModel):
    capability_id: UUID
    job_id: UUID
    operation: str = Field(min_length=1, max_length=100)
    scenario: SimulationScenario = SimulationScenario.SUCCESS
    payload: dict[str, Any] = Field(default_factory=dict)


class ExecutionBody(DryRunBody):
    technical_approval_id: UUID
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_backoff_seconds: int = Field(default=1, ge=0, le=300)


class ReasonBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


@router.get("/providers")
async def providers(
    session: Session,
    context: Annotated[SessionContext, Depends(require_session_context)],
) -> dict[str, Any]:
    service = ProviderService(session)
    return {
        "items": await service.list_providers(actor=context.actor),
        "feature_flags": await service.feature_flags(actor=context.actor),
        "productive_execution_visible": False,
    }


@router.post("/providers/simulation")
async def configure_simulation_provider(
    body: ProviderConfigurationBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_admin_actor)],
) -> dict[str, Any]:
    async with session.begin():
        service = ProviderService(session)
        provider = await service.configure_simulation_provider(actor=actor, **body.model_dump())
    return await ProviderService(session).provider_dict(provider)


@router.post("/providers/{provider_id}/technical-approvals")
async def approve_technical_execution(
    provider_id: UUID,
    body: TechnicalApprovalBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_admin_actor)],
) -> dict[str, Any]:
    async with session.begin():
        approval = await ProviderService(session).approve_technical_execution(
            actor=actor,
            provider_id=provider_id,
            capability_id=body.capability_id,
            job_id=body.job_id,
            reason=body.reason,
        )
    return {
        "id": str(approval.id),
        "job_id": str(approval.job_id),
        "job_revision": approval.job_revision,
        "status": approval.status.value,
        "reason": approval.reason,
    }


@router.post("/providers/{provider_id}/dry-runs")
async def create_dry_run(
    provider_id: UUID,
    body: DryRunBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, Any]:
    async with session.begin():
        result = await ProviderService(session).create_dry_run(
            actor=actor,
            provider_id=provider_id,
            idempotency_key=idempotency_key,
            **body.model_dump(),
        )
    return {
        "execution": await ProviderService(session).execution_dict(result.order, detailed=True),
        "replayed": result.replayed,
        "validation_errors": result.validation_errors,
    }


@router.post("/providers/{provider_id}/executions")
async def create_execution(
    provider_id: UUID,
    body: ExecutionBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, Any]:
    async with session.begin():
        result = await ProviderService(session).create_execution(
            actor=actor,
            provider_id=provider_id,
            idempotency_key=idempotency_key,
            **body.model_dump(),
        )
    return {
        "execution": await ProviderService(session).execution_dict(result.order, detailed=True),
        "replayed": result.replayed,
    }


@router.get("/executions")
async def executions(
    session: Session,
    context: Annotated[SessionContext, Depends(require_session_context)],
) -> dict[str, Any]:
    return {"items": await ProviderService(session).list_executions(actor=context.actor)}


@router.get("/executions/{order_id}")
async def execution_detail(
    order_id: UUID,
    session: Session,
    context: Annotated[SessionContext, Depends(require_session_context)],
) -> dict[str, Any]:
    return await ProviderService(session).execution_detail(actor=context.actor, order_id=order_id)


@router.post("/executions/{order_id}/resume")
async def resume_execution(
    order_id: UUID,
    body: ReasonBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_admin_actor)],
) -> dict[str, Any]:
    async with session.begin():
        order = await ProviderService(session).resume_execution(
            actor=actor, order_id=order_id, reason=body.reason
        )
    return await ProviderService(session).execution_dict(order, detailed=True)


@router.post("/executions/{order_id}/discard")
async def discard_execution(
    order_id: UUID,
    body: ReasonBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_admin_actor)],
) -> dict[str, Any]:
    async with session.begin():
        order = await ProviderService(session).discard_execution(
            actor=actor, order_id=order_id, reason=body.reason
        )
    return await ProviderService(session).execution_dict(order, detailed=True)


@router.post("/provider-callbacks/{provider_id}")
async def provider_callback(
    provider_id: UUID,
    request: Request,
    session: Session,
    event_id: Annotated[str, Header(alias="X-Provider-Event-ID")],
    correlation_id: Annotated[UUID, Header(alias="X-Correlation-ID")],
    timestamp: Annotated[str, Header(alias="X-Provider-Timestamp")],
    signature: Annotated[str, Header(alias="X-Provider-Signature")],
) -> dict[str, Any]:
    raw_body = await request.body()
    async with session.begin():
        receipt = await CallbackService(session).accept(
            provider_id=provider_id,
            event_id=event_id,
            correlation_id=correlation_id,
            timestamp=timestamp,
            signature=signature,
            raw_body=raw_body,
        )
    return {
        "receipt_id": str(receipt.id),
        "status": receipt.status.value,
        "correlation_id": str(receipt.correlation_id),
    }
