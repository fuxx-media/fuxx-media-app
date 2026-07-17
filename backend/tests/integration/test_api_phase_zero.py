"""Session-authenticated Phase 0 API regression tests."""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.domain.enums import RoleName
from mediaos.domain.models import Tenant, User, UserRole
from mediaos.main import app
from mediaos.security import hash_password

pytestmark = pytest.mark.integration
PASSWORD = "phase-one-test-password"


async def _login(
    client: AsyncClient,
    session: AsyncSession,
    tenant: Tenant,
    role: RoleName = RoleName.ADMIN,
) -> str:
    user = User(
        tenant_id=tenant.id,
        email=f"api-{uuid4().hex}@example.com",
        password_hash=hash_password(PASSWORD),
    )
    session.add(user)
    await session.flush()
    session.add(UserRole(user_id=user.id, role=role))
    await session.commit()
    response = await client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": tenant.slug, "email": user.email, "password": PASSWORD},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


async def test_channel_job_transition_timeline_cost_and_audit_api(
    integration_session: AsyncSession, tenant: Tenant
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        unauthorized = await client.post(
            "/api/v1/channels", json={"name": "Unauthorized", "slug": "unauthorized"}
        )
        assert unauthorized.status_code == 401
        assert unauthorized.json()["code"] == "AUTHENTICATION_REQUIRED"

        csrf = await _login(client, integration_session, tenant)
        write_headers = {"X-CSRF-Token": csrf, "Idempotency-Key": uuid4().hex}
        channel_response = await client.post(
            "/api/v1/channels",
            headers=write_headers,
            json={"name": "API", "slug": f"api-{uuid4().hex}"},
        )
        assert channel_response.status_code == 201
        channel_id = channel_response.json()["id"]

        job_response = await client.post(
            "/api/v1/jobs",
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": uuid4().hex},
            json={
                "channel_id": channel_id,
                "title": "API proof",
                "budget_limit_cents": 100,
            },
        )
        assert job_response.status_code == 201
        job_id = job_response.json()["id"]

        transition_response = await client.post(
            f"/api/v1/jobs/{job_id}/transitions",
            headers={"X-CSRF-Token": csrf},
            json={"target_state": "TOPIC_APPROVED", "expected_version": 1},
        )
        assert transition_response.status_code == 200
        assert transition_response.json()["version"] == 2

        conflict_response = await client.post(
            f"/api/v1/jobs/{job_id}/transitions",
            headers={"X-CSRF-Token": csrf},
            json={"target_state": "RESEARCHING", "expected_version": 1},
        )
        assert conflict_response.status_code == 409
        assert conflict_response.json()["code"] == "VERSION_CONFLICT"

        timeline = await client.get(f"/api/v1/jobs/{job_id}/timeline")
        costs = await client.get(f"/api/v1/jobs/{job_id}/costs")
        audit = await client.get(f"/api/v1/jobs/{job_id}/audit")
        assert timeline.status_code == costs.status_code == audit.status_code == 200
        assert len(timeline.json()) == 1
        assert costs.json() == []
        assert [event["event_type"] for event in audit.json()] == [
            "CONTENT_JOB_CREATED",
            "WORKFLOW_TRANSITION",
        ]


async def test_api_404_uses_error_envelope(
    integration_session: AsyncSession, tenant: Tenant
) -> None:
    missing_id = uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await _login(client, integration_session, tenant)
        response = await client.get(f"/api/v1/jobs/{missing_id}/timeline")
    assert response.status_code == 404
    payload = response.json()
    assert payload["code"] == "JOB_NOT_FOUND"
    assert payload["correlation_id"]
