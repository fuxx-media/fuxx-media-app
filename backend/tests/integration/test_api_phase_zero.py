"""Phase 0 API positive and negative integration tests."""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from mediaos.main import app

pytestmark = pytest.mark.integration
HEADERS = {"X-Actor-Id": str(uuid4()), "X-Actor-Type": "USER"}


async def test_channel_job_transition_timeline_cost_and_audit_api() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        unauthorized = await client.post(
            "/api/v1/channels", json={"name": "Unauthorized", "slug": "unauthorized"}
        )
        assert unauthorized.status_code == 401
        assert unauthorized.json()["code"] == "HTTP_401"

        channel_response = await client.post(
            "/api/v1/channels",
            headers=HEADERS,
            json={"name": "API", "slug": f"api-{uuid4().hex}"},
        )
        assert channel_response.status_code == 201
        channel_id = channel_response.json()["id"]

        job_response = await client.post(
            "/api/v1/jobs",
            headers=HEADERS,
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
            headers=HEADERS,
            json={"target_state": "TOPIC_APPROVED", "expected_version": 1},
        )
        assert transition_response.status_code == 200
        assert transition_response.json()["version"] == 2

        conflict_response = await client.post(
            f"/api/v1/jobs/{job_id}/transitions",
            headers=HEADERS,
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


async def test_api_404_uses_error_envelope() -> None:
    missing_id = uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/v1/jobs/{missing_id}/timeline")
    assert response.status_code == 404
    payload = response.json()
    assert payload["code"] == "JOB_NOT_FOUND"
    assert payload["correlation_id"]
