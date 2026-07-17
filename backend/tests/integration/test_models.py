"""PostgreSQL model and constraint integration tests."""

from datetime import UTC
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.domain.enums import (
    ActorType,
    ApprovalStatus,
    ArtifactKind,
    ProviderCallStatus,
    TaskStatus,
)
from mediaos.domain.models import (
    ApprovalRequest,
    Artifact,
    AuditEvent,
    Channel,
    ContentJob,
    CostEntry,
    JobTask,
    ProviderCall,
    ProviderConfiguration,
    Tenant,
)

pytestmark = pytest.mark.integration


async def test_all_core_entities_use_uuid_utc_and_integer_cents(
    integration_session: AsyncSession, tenant: Tenant
) -> None:
    actor_id = uuid4()
    channel = Channel(tenant_id=tenant.id, name="Integration", slug=f"integration-{uuid4().hex}")
    provider = ProviderConfiguration(name=f"provider-{uuid4().hex}", provider_type="fake")
    integration_session.add_all([channel, provider])
    await integration_session.flush()
    job = ContentJob(
        tenant_id=tenant.id,
        channel_id=channel.id,
        title="Model proof",
        budget_limit_cents=1_000,
    )
    integration_session.add(job)
    await integration_session.flush()
    call = ProviderCall(
        job_id=job.id,
        provider_configuration_id=provider.id,
        status=ProviderCallStatus.SUCCEEDED,
        cost_cents=125,
    )
    integration_session.add(call)
    await integration_session.flush()
    entities = [
        ApprovalRequest(
            job_id=job.id,
            status=ApprovalStatus.PENDING,
            requested_by=actor_id,
        ),
        Artifact(
            job_id=job.id,
            kind=ArtifactKind.VIDEO,
            bucket="proof",
            object_key=f"{uuid4()}.mp4",
            sha256="a" * 64,
            size_bytes=42,
        ),
        AuditEvent(
            tenant_id=tenant.id,
            job_id=job.id,
            actor_id=actor_id,
            actor_type=ActorType.USER,
            event_type="MODEL_PROOF",
            payload={},
        ),
        CostEntry(
            job_id=job.id,
            provider_call_id=call.id,
            category="proof",
            amount_cents=125,
        ),
        JobTask(job_id=job.id, task_type="HEARTBEAT", status=TaskStatus.PENDING),
    ]
    integration_session.add_all(entities)
    await integration_session.commit()

    assert all(entity.id.version == 4 for entity in [channel, provider, job, call, *entities])
    assert job.created_at.tzinfo is not None
    assert job.created_at.utcoffset() == UTC.utcoffset(job.created_at)
    assert call.cost_cents == 125


async def test_negative_cent_amount_is_rejected(
    integration_session: AsyncSession, tenant: Tenant
) -> None:
    channel = Channel(tenant_id=tenant.id, name="Constraint", slug=f"constraint-{uuid4().hex}")
    integration_session.add(channel)
    await integration_session.flush()
    integration_session.add(
        ContentJob(
            tenant_id=tenant.id,
            channel_id=channel.id,
            title="Invalid",
            budget_limit_cents=-1,
        )
    )
    with pytest.raises(IntegrityError):
        await integration_session.flush()


async def test_audit_event_is_immutable_in_database(
    integration_session: AsyncSession, tenant: Tenant
) -> None:
    event = AuditEvent(
        tenant_id=tenant.id,
        actor_id=uuid4(),
        actor_type=ActorType.SYSTEM,
        event_type="IMMUTABLE",
        payload={},
    )
    integration_session.add(event)
    await integration_session.commit()
    with pytest.raises(DBAPIError):
        await integration_session.execute(
            update(AuditEvent).where(AuditEvent.id == event.id).values(event_type="CHANGED")
        )
        await integration_session.commit()
