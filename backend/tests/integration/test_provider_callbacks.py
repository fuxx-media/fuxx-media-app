"""Signed callback, timestamp, correlation, and replay protection tests."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from backend.tests.integration.provider_helpers import (
    configure_provider,
    login,
    setup_provider_context,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.domain.enums import ExecutionStatus, SimulationScenario
from mediaos.domain.models import (
    AuditEvent,
    CallbackReceipt,
    ExecutionOrder,
    ProviderConfiguration,
    ProviderFeatureFlags,
    Tenant,
)
from mediaos.main import app

pytestmark = pytest.mark.integration
CALLBACK_SECRET = "local-callback-test-secret"


def signed_headers(
    raw: bytes,
    correlation_id: str,
    *,
    event_id: str,
    timestamp: int | None = None,
    secret: str = CALLBACK_SECRET,
) -> dict[str, str]:
    timestamp_value = timestamp or int(datetime.now(UTC).timestamp())
    timestamp_text = str(timestamp_value)
    signature = hmac.new(
        secret.encode(), timestamp_text.encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Provider-Event-ID": event_id,
        "X-Correlation-ID": correlation_id,
        "X-Provider-Timestamp": timestamp_text,
        "X-Provider-Signature": signature,
    }


async def test_callback_signature_timestamp_replay_correlation_and_audit(
    integration_session: AsyncSession,
    tenant: Tenant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEDIAOS_SIMULATION_CALLBACK_SECRET", CALLBACK_SECRET)
    context = await setup_provider_context(integration_session, tenant)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_csrf = await login(client, context, context.admin)
        provider_payload, provider_id, capability_id = await configure_provider(
            client, admin_csrf
        )
        technical = await client.post(
            f"/api/v1/providers/{provider_id}/technical-approvals",
            headers={"X-CSRF-Token": admin_csrf},
            json={
                "capability_id": capability_id,
                "job_id": str(context.job.id),
                "reason": "Callback integration test",
            },
        )
        assert technical.status_code == 200
        execution = await client.post(
            f"/api/v1/providers/{provider_id}/executions",
            headers={
                "X-CSRF-Token": admin_csrf,
                "Idempotency-Key": "callback-execution",
            },
            json={
                "capability_id": capability_id,
                "job_id": str(context.job.id),
                "operation": "SIMULATE_CASE",
                "scenario": SimulationScenario.AMBIGUOUS_STATUS.value,
                "technical_approval_id": technical.json()["id"],
                "max_attempts": 1,
                "retry_backoff_seconds": 0,
                "payload": {},
            },
        )
        assert execution.status_code == 200
        order = execution.json()["execution"]
        raw = json.dumps(
            {"status": "PROCESSED", "provider_secret": "sensitive-callback-value"}
        ).encode()

        disabled = await client.post(
            f"/api/v1/provider-callbacks/{provider_id}",
            content=raw,
            headers=signed_headers(raw, order["correlation_id"], event_id="disabled-event"),
        )
        assert disabled.status_code == 422

        provider = await integration_session.get(ProviderConfiguration, UUID(provider_id))
        flags = await integration_session.scalar(
            select(ProviderFeatureFlags).where(ProviderFeatureFlags.tenant_id == tenant.id)
        )
        assert provider is not None and flags is not None
        provider.callback_enabled = True
        flags.callback_intake_enabled = True
        await integration_session.commit()

        valid_headers = signed_headers(
            raw, order["correlation_id"], event_id="callback-valid"
        )
        valid = await client.post(
            f"/api/v1/provider-callbacks/{provider_id}", content=raw, headers=valid_headers
        )
        assert valid.status_code == 200, valid.text
        assert valid.json()["status"] == "ACCEPTED"
        stored_order = await integration_session.get(ExecutionOrder, UUID(order["id"]))
        await integration_session.refresh(stored_order)
        assert stored_order is not None and stored_order.status == ExecutionStatus.SUCCEEDED

        replay = await client.post(
            f"/api/v1/provider-callbacks/{provider_id}", content=raw, headers=valid_headers
        )
        assert replay.status_code == 409

        invalid_signature = await client.post(
            f"/api/v1/provider-callbacks/{provider_id}",
            content=raw,
            headers=signed_headers(
                raw,
                order["correlation_id"],
                event_id="callback-invalid-signature",
                secret="wrong-local-secret",
            ),
        )
        assert invalid_signature.status_code == 422

        expired_timestamp = int((datetime.now(UTC) - timedelta(minutes=10)).timestamp())
        expired = await client.post(
            f"/api/v1/provider-callbacks/{provider_id}",
            content=raw,
            headers=signed_headers(
                raw,
                order["correlation_id"],
                event_id="callback-expired",
                timestamp=expired_timestamp,
            ),
        )
        assert expired.status_code == 422

        unknown_correlation = await client.post(
            f"/api/v1/provider-callbacks/{provider_id}",
            content=raw,
            headers=signed_headers(
                raw,
                str(uuid4()),
                event_id="callback-unknown-correlation",
            ),
        )
        assert unknown_correlation.status_code == 422
        assert "local-callback-test-secret" not in str(provider_payload)

    assert await integration_session.scalar(select(func.count(CallbackReceipt.id))) == 1
    receipt = await integration_session.scalar(select(CallbackReceipt))
    assert receipt is not None
    assert receipt.signature_valid is True
    assert receipt.payload_hash == hashlib.sha256(raw).hexdigest()
    assert "sensitive-callback-value" not in str(receipt.raw_payload)
    assert "sensitive-callback-value" not in str(receipt.normalized_response)
    event_types = set(
        (await integration_session.scalars(select(AuditEvent.event_type))).all()
    )
    assert "PROVIDER_CALLBACK_ACCEPTED" in event_types
