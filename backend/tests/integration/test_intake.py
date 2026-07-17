"""Authenticated, idempotent, tenant-scoped private intake tests."""

import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.domain.enums import RoleName, TaskStatus
from mediaos.domain.models import (
    AuditEvent,
    Channel,
    ContentJob,
    IdempotencyRecord,
    JobAttachment,
    JobTask,
    StoredFile,
    Tenant,
    User,
    UserRole,
)
from mediaos.main import app
from mediaos.security import hash_password

pytestmark = pytest.mark.integration
PASSWORD = "intake-test-password"


async def setup_access(session: AsyncSession, tenant: Tenant) -> tuple[User, Channel]:
    user = User(
        tenant_id=tenant.id,
        email=f"intake-{uuid4().hex}@example.com",
        password_hash=hash_password(PASSWORD),
    )
    channel = Channel(tenant_id=tenant.id, name="Intake", slug=f"intake-{uuid4().hex}")
    session.add_all([user, channel])
    await session.flush()
    session.add(UserRole(user_id=user.id, role=RoleName.BACKOFFICE))
    await session.commit()
    return user, channel


async def login(client: AsyncClient, tenant: Tenant, user: User) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": tenant.slug, "email": user.email, "password": PASSWORD},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def intake_data(channel: Channel) -> dict[str, str]:
    return {
        "channel_id": str(channel.id),
        "title": "Incoming verified document",
        "budget_limit_cents": "500",
    }


async def test_upload_creation_download_deduplication_queue_and_audit(
    integration_session: AsyncSession, tenant: Tenant
) -> None:
    user, channel = await setup_access(integration_session, tenant)
    pdf = b"%PDF-1.7\nverified content\n%%EOF"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        csrf = await login(client, tenant, user)
        first = await client.post(
            "/api/v1/intakes",
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": "intake-one"},
            data=intake_data(channel),
            files={"upload": ("not-trusted-name.exe", pdf, "application/pdf")},
        )
        assert first.status_code == 201
        payload = first.json()
        assert payload["replayed"] is False
        replay = await client.post(
            "/api/v1/intakes",
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": "intake-one"},
            data=intake_data(channel),
            files={"upload": ("changed-name.pdf", pdf, "application/pdf")},
        )
        assert replay.status_code == 201
        assert replay.json()["job_id"] == payload["job_id"]
        assert replay.json()["replayed"] is True
        second = await client.post(
            "/api/v1/intakes",
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": "intake-two"},
            data={**intake_data(channel), "title": "Second reference"},
            files={"upload": ("same-content.pdf", pdf, "application/pdf")},
        )
        assert second.status_code == 201
        assert second.json()["stored_file_id"] == payload["stored_file_id"]
        download = await client.get(f"/api/v1/files/{payload['stored_file_id']}/download")
        assert download.status_code == 200
        assert download.content == pdf

    assert await integration_session.scalar(select(func.count(StoredFile.id))) == 1
    assert await integration_session.scalar(select(func.count(JobAttachment.id))) == 2
    assert await integration_session.scalar(select(func.count(ContentJob.id))) == 2
    task = await integration_session.get(JobTask, uuid4())
    assert task is None
    event_types = set((await integration_session.scalars(select(AuditEvent.event_type))).all())
    assert {"INTAKE_CREATED", "FILE_DOWNLOADED"}.issubset(event_types)


async def test_invalid_mime_size_and_cross_tenant_channel_are_rejected(
    integration_session: AsyncSession, tenant: Tenant
) -> None:
    user, channel = await setup_access(integration_session, tenant)
    other_tenant = Tenant(name="Other", slug=f"other-{uuid4().hex}")
    integration_session.add(other_tenant)
    await integration_session.flush()
    other_channel = Channel(tenant_id=other_tenant.id, name="Other", slug=f"other-{uuid4().hex}")
    integration_session.add(other_channel)
    await integration_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        csrf = await login(client, tenant, user)
        invalid_mime = await client.post(
            "/api/v1/intakes",
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": uuid4().hex},
            data=intake_data(channel),
            files={"upload": ("fake.png", b"%PDF-1.7\n", "image/png")},
        )
        assert invalid_mime.status_code == 422
        too_large = await client.post(
            "/api/v1/intakes",
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": uuid4().hex},
            data=intake_data(channel),
            files={
                "upload": (
                    "large.txt",
                    b"a" * (10 * 1024 * 1024 + 1),
                    "text/plain",
                )
            },
        )
        assert too_large.status_code == 422
        cross_tenant = await client.post(
            "/api/v1/intakes",
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": uuid4().hex},
            data={**intake_data(channel), "channel_id": str(other_channel.id)},
        )
        assert cross_tenant.status_code == 404


async def test_parallel_identical_requests_create_one_effect(
    integration_session: AsyncSession, tenant: Tenant
) -> None:
    user, channel = await setup_access(integration_session, tenant)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        csrf = await login(client, tenant, user)

        async def submit():
            return await client.post(
                "/api/v1/intakes",
                headers={"X-CSRF-Token": csrf, "Idempotency-Key": "parallel-same"},
                data=intake_data(channel),
            )

        first, second = await asyncio.gather(submit(), submit())
        assert first.status_code == second.status_code == 201
        assert first.json()["job_id"] == second.json()["job_id"]
        assert sorted([first.json()["replayed"], second.json()["replayed"]]) == [False, True]
    assert await integration_session.scalar(select(func.count(ContentJob.id))) == 1
    assert await integration_session.scalar(select(func.count(JobTask.id))) == 1
    assert await integration_session.scalar(select(func.count(IdempotencyRecord.id))) == 1
    queued = await integration_session.scalar(select(JobTask))
    assert queued is not None
    assert queued.status == TaskStatus.PENDING
