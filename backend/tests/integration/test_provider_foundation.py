"""Phase 3 gates, dry-run, outbox, retry, recovery, and audit tests."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from backend.tests.integration.provider_helpers import (
    add_user,
    configure_provider,
    create_approved_job,
    login,
    setup_provider_context,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.application.provider_contract import ProviderExecutionResult
from mediaos.database import get_session_factory
from mediaos.domain.enums import (
    ExecutionStatus,
    OutboxStatus,
    RoleName,
    SimulationScenario,
    TechnicalApprovalStatus,
)
from mediaos.domain.models import (
    ApprovalRequest,
    AuditEvent,
    DryRunResult,
    ExecutionAttempt,
    ExecutionOrder,
    OutboxEvent,
    ProviderCapability,
    ProviderConfiguration,
    TechnicalApproval,
    Tenant,
)
from mediaos.infrastructure.provider_execution_repository import (
    ProviderExecutionRepository,
)
from mediaos.main import app
from mediaos.worker.provider_execution import process_one_provider_execution

pytestmark = pytest.mark.integration


def headers(csrf: str, key: str | None = None) -> dict[str, str]:
    result = {"X-CSRF-Token": csrf}
    if key:
        result["Idempotency-Key"] = key
    return result


async def technical_approval(
    client: AsyncClient,
    csrf: str,
    provider_id: str,
    capability_id: str,
    job_id: object,
) -> str:
    response = await client.post(
        f"/api/v1/providers/{provider_id}/technical-approvals",
        headers=headers(csrf),
        json={
            "capability_id": capability_id,
            "job_id": str(job_id),
            "reason": "Approved for local simulation only",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def execution_body(
    capability_id: str,
    job_id: object,
    technical_approval_id: str,
    scenario: SimulationScenario,
    *,
    max_attempts: int = 3,
) -> dict[str, object]:
    return {
        "capability_id": capability_id,
        "job_id": str(job_id),
        "operation": "SIMULATE_CASE",
        "scenario": scenario.value,
        "technical_approval_id": technical_approval_id,
        "max_attempts": max_attempts,
        "retry_backoff_seconds": 0,
        "payload": {"customer_token": "must-be-masked"},
    }


async def create_execution(
    client: AsyncClient,
    csrf: str,
    provider_id: str,
    body: dict[str, object],
    key: str,
) -> dict[str, object]:
    response = await client.post(
        f"/api/v1/providers/{provider_id}/executions",
        headers=headers(csrf, key),
        json=body,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_configuration_dry_run_masking_gates_idempotency_roles_and_tenants(
    integration_session: AsyncSession, tenant: Tenant
) -> None:
    context = await setup_provider_context(integration_session, tenant)
    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as admin_client,
        AsyncClient(transport=transport, base_url="http://test") as backoffice_client,
        AsyncClient(transport=transport, base_url="http://test") as reviewer_client,
    ):
        admin_csrf = await login(admin_client, context, context.admin)
        backoffice_csrf = await login(backoffice_client, context, context.backoffice)
        reviewer_csrf = await login(reviewer_client, context, context.reviewer)
        provider, provider_id, capability_id = await configure_provider(
            admin_client, admin_csrf
        )
        serialized = str(provider)
        assert "must-not-leak" not in serialized
        assert "secret_value" not in serialized
        assert provider["production_enabled"] is False
        assert provider["callback_enabled"] is False
        assert provider["secret_reference"]["configured"] is True

        dry_body = {
            "capability_id": capability_id,
            "job_id": str(context.job.id),
            "operation": "SIMULATE_CASE",
            "scenario": "SUCCESS",
            "payload": {"api_token": "must-not-leak"},
        }
        first = await backoffice_client.post(
            f"/api/v1/providers/{provider_id}/dry-runs",
            headers=headers(backoffice_csrf, "dry-run-one"),
            json=dry_body,
        )
        assert first.status_code == 200, first.text
        first_payload = first.json()
        assert first_payload["replayed"] is False
        assert first_payload["execution"]["status"] == "DRY_RUN_SUCCEEDED"
        assert first_payload["execution"]["external_effect"] is False
        assert "must-not-leak" not in str(first_payload)
        replay = await backoffice_client.post(
            f"/api/v1/providers/{provider_id}/dry-runs",
            headers=headers(backoffice_csrf, "dry-run-one"),
            json=dry_body,
        )
        assert replay.status_code == 200
        assert replay.json()["replayed"] is True
        assert replay.json()["execution"]["id"] == first_payload["execution"]["id"]

        parallel_body = {**dry_body, "scenario": "DELAYED_RESPONSE"}

        async def submit_parallel() -> object:
            response = await backoffice_client.post(
                f"/api/v1/providers/{provider_id}/dry-runs",
                headers=headers(backoffice_csrf, "dry-run-parallel"),
                json=parallel_body,
            )
            assert response.status_code == 200
            return response.json()

        parallel = await asyncio.gather(submit_parallel(), submit_parallel())
        assert parallel[0]["execution"]["id"] == parallel[1]["execution"]["id"]
        assert sorted([parallel[0]["replayed"], parallel[1]["replayed"]]) == [False, True]

        reviewer_dry_run = await reviewer_client.post(
            f"/api/v1/providers/{provider_id}/dry-runs",
            headers=headers(reviewer_csrf, "reviewer-forbidden"),
            json=dry_body,
        )
        assert reviewer_dry_run.status_code == 403
        reviewer_configuration = await reviewer_client.post(
            "/api/v1/providers/simulation",
            headers=headers(reviewer_csrf),
            json={
                "name": "Forbidden",
                "secret_reference_name": "forbidden",
                "secret_environment_variable": "MEDIAOS_FORBIDDEN",
                "signature_profile_name": "forbidden",
                "capability_operation": "SIMULATE_CASE",
            },
        )
        assert reviewer_configuration.status_code == 403

        other_tenant = Tenant(name="Other Provider Tenant", slug=f"other-{uuid4().hex}")
        integration_session.add(other_tenant)
        await integration_session.flush()
        other_user = await add_user(
            integration_session, other_tenant, "other-provider", RoleName.BACKOFFICE
        )
        await integration_session.commit()
        other_context = type(context)(other_tenant, other_user, other_user, other_user, context.job)
        async with AsyncClient(transport=transport, base_url="http://test") as other_client:
            other_csrf = await login(other_client, other_context, other_user)
            cross_tenant = await other_client.post(
                f"/api/v1/providers/{provider_id}/dry-runs",
                headers=headers(other_csrf, "cross-tenant"),
                json=dry_body,
            )
            assert cross_tenant.status_code == 404

    assert (
        await integration_session.scalar(select(func.count(DryRunResult.id))) == 2
    )
    assert await integration_session.scalar(select(func.count(OutboxEvent.id))) == 0
    events = set(
        (await integration_session.scalars(select(AuditEvent.event_type))).all()
    )
    assert {"SIMULATION_PROVIDER_CONFIGURED", "PROVIDER_DRY_RUN_COMPLETED"}.issubset(events)


async def test_missing_secret_approval_required_fields_and_stale_approval_are_blocked(
    integration_session: AsyncSession, tenant: Tenant
) -> None:
    context = await setup_provider_context(integration_session, tenant)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_csrf = await login(client, context, context.admin)
        provider, provider_id, capability_id = await configure_provider(client, admin_csrf)
        without_approval = await create_approved_job(
            integration_session,
            tenant,
            context.backoffice,
            context.reviewer,
            title="No approval",
        )
        await integration_session.execute(
            delete(ApprovalRequest).where(ApprovalRequest.job_id == without_approval.id)
        )
        missing_field = await create_approved_job(
            integration_session,
            tenant,
            context.backoffice,
            context.reviewer,
            title="Missing category",
            category=None,
        )
        await integration_session.commit()
        body = {
            "capability_id": capability_id,
            "job_id": str(without_approval.id),
            "operation": "SIMULATE_CASE",
            "scenario": "SUCCESS",
            "payload": {},
        }
        blocked = await client.post(
            f"/api/v1/providers/{provider_id}/dry-runs",
            headers=headers(admin_csrf, "missing-approval"),
            json=body,
        )
        assert blocked.status_code == 409
        invalid_dry_run = await client.post(
            f"/api/v1/providers/{provider_id}/dry-runs",
            headers=headers(admin_csrf, "missing-required-field"),
            json={**body, "job_id": str(missing_field.id)},
        )
        assert invalid_dry_run.status_code == 200
        assert invalid_dry_run.json()["execution"]["status"] == "DRY_RUN_FAILED"
        assert invalid_dry_run.json()["validation_errors"]

        no_secret = ProviderConfiguration(
            tenant_id=tenant.id,
            name="No secret",
            provider_type="SIMULATION",
            enabled=True,
            settings={"mode": "local"},
        )
        integration_session.add(no_secret)
        await integration_session.flush()
        no_secret_capability = ProviderCapability(
            provider_configuration_id=no_secret.id,
            name="No secret capability",
            operation="SIMULATE_CASE",
            required_fields=["title"],
        )
        integration_session.add(no_secret_capability)
        await integration_session.commit()
        secret_blocked = await client.post(
            f"/api/v1/providers/{no_secret.id}/dry-runs",
            headers=headers(admin_csrf, "missing-secret"),
            json={
                **body,
                "job_id": str(context.job.id),
                "capability_id": str(no_secret_capability.id),
            },
        )
        assert secret_blocked.status_code == 422

        context.job.version += 1
        await integration_session.commit()
        stale = await client.post(
            f"/api/v1/providers/{provider_id}/dry-runs",
            headers=headers(admin_csrf, "stale-approval"),
            json={**body, "job_id": str(context.job.id)},
        )
        assert stale.status_code == 409
        assert provider["production_enabled"] is False


async def test_outbox_worker_retry_dead_letter_manual_resume_discard_and_idempotency(
    integration_session: AsyncSession, tenant: Tenant
) -> None:
    context = await setup_provider_context(integration_session, tenant)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_csrf = await login(client, context, context.admin)
        _, provider_id, capability_id = await configure_provider(client, admin_csrf)
        approval_id = await technical_approval(
            client, admin_csrf, provider_id, capability_id, context.job.id
        )
        success_body = execution_body(
            capability_id,
            context.job.id,
            approval_id,
            SimulationScenario.SUCCESS,
        )
        success = await create_execution(
            client, admin_csrf, provider_id, success_body, "execution-success"
        )
        success_id = str(success["execution"]["id"])
        assert success["execution"]["status"] == "QUEUED"
        assert await integration_session.scalar(select(func.count(OutboxEvent.id))) == 1
        assert await process_one_provider_execution(worker_id="test-success") is True
        success_detail = await client.get(f"/api/v1/executions/{success_id}")
        assert success_detail.status_code == 200
        assert success_detail.json()["status"] == "SUCCEEDED"
        assert success_detail.json()["external_effect"] is False
        replay = await create_execution(
            client, admin_csrf, provider_id, success_body, "execution-success"
        )
        assert replay["replayed"] is True
        assert replay["execution"]["id"] == success_id

        temporary = await create_execution(
            client,
            admin_csrf,
            provider_id,
            execution_body(
                capability_id,
                context.job.id,
                approval_id,
                SimulationScenario.TEMPORARY_ERROR,
                max_attempts=2,
            ),
            "execution-temporary",
        )
        temporary_id = str(temporary["execution"]["id"])
        assert await process_one_provider_execution(worker_id="test-retry-1") is True
        retry_detail = await client.get(f"/api/v1/executions/{temporary_id}")
        assert retry_detail.json()["status"] == "RETRY"
        assert retry_detail.json()["retry_plans"][0]["backoff_seconds"] == 0
        assert await process_one_provider_execution(worker_id="test-retry-2") is True
        dead_detail = await client.get(f"/api/v1/executions/{temporary_id}")
        assert dead_detail.json()["status"] == "DEAD_LETTER"
        assert len(dead_detail.json()["attempts"]) == 2

        permanent = await create_execution(
            client,
            admin_csrf,
            provider_id,
            execution_body(
                capability_id,
                context.job.id,
                approval_id,
                SimulationScenario.PERMANENT_ERROR,
            ),
            "execution-permanent",
        )
        permanent_id = str(permanent["execution"]["id"])
        assert await process_one_provider_execution(worker_id="test-permanent") is True
        permanent_detail = await client.get(f"/api/v1/executions/{permanent_id}")
        assert permanent_detail.json()["status"] == "DEAD_LETTER"
        assert len(permanent_detail.json()["attempts"]) == 1

        resumed = await client.post(
            f"/api/v1/executions/{permanent_id}/resume",
            headers=headers(admin_csrf),
            json={"reason": "Controlled local retry"},
        )
        assert resumed.status_code == 200
        assert resumed.json()["status"] == "QUEUED"
        assert await process_one_provider_execution(worker_id="test-resumed") is True
        discarded = await client.post(
            f"/api/v1/executions/{permanent_id}/discard",
            headers=headers(admin_csrf),
            json={"reason": "Simulation evidence retained and closed"},
        )
        assert discarded.status_code == 200
        assert discarded.json()["status"] == "DISCARDED"
        assert discarded.json()["discard_reason"]

    event_types = set(
        (await integration_session.scalars(select(AuditEvent.event_type))).all()
    )
    assert {
        "PROVIDER_EXECUTION_QUEUED",
        "PROVIDER_EXECUTION_SUCCEEDED",
        "PROVIDER_EXECUTION_RETRY_SCHEDULED",
        "PROVIDER_EXECUTION_DEAD_LETTER",
        "PROVIDER_EXECUTION_MANUALLY_RESUMED",
        "PROVIDER_EXECUTION_DISCARDED",
    }.issubset(event_types)


async def test_parallel_claim_worker_recovery_ambiguous_status_and_revision_invalidation(
    integration_session: AsyncSession, tenant: Tenant
) -> None:
    context = await setup_provider_context(integration_session, tenant)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_csrf = await login(client, context, context.admin)
        _, provider_id, capability_id = await configure_provider(client, admin_csrf)
        approval_id = await technical_approval(
            client, admin_csrf, provider_id, capability_id, context.job.id
        )
        created_ids: list[str] = []
        for scenario in (SimulationScenario.SUCCESS, SimulationScenario.DUPLICATE_RESPONSE):
            created = await create_execution(
                client,
                admin_csrf,
                provider_id,
                execution_body(capability_id, context.job.id, approval_id, scenario),
                f"parallel-{scenario.value}",
            )
            created_ids.append(str(created["execution"]["id"]))

        factory = get_session_factory()
        async with factory() as first_session, factory() as second_session:
            async with first_session.begin():
                first = await ProviderExecutionRepository(first_session).claim_next(
                    worker_id="parallel-one"
                )
                assert first is not None
                async with second_session.begin():
                    second = await ProviderExecutionRepository(second_session).claim_next(
                        worker_id="parallel-two"
                    )
                    assert second is not None
                    assert second.order_id != first.order_id
                    await ProviderExecutionRepository(second_session).succeed(
                        second,
                        ProviderExecutionResult(
                            provider_status="PROCESSED",
                            normalized_status="SUCCEEDED",
                            payload={"external_effect": False},
                        ),
                    )
            async with first_session.begin():
                await ProviderExecutionRepository(first_session).succeed(
                    first,
                    ProviderExecutionResult(
                        provider_status="PROCESSED",
                        normalized_status="SUCCEEDED",
                        payload={"external_effect": False},
                    ),
                )

        ambiguous = await create_execution(
            client,
            admin_csrf,
            provider_id,
            execution_body(
                capability_id,
                context.job.id,
                approval_id,
                SimulationScenario.AMBIGUOUS_STATUS,
            ),
            "execution-ambiguous",
        )
        ambiguous_id = str(ambiguous["execution"]["id"])
        assert await process_one_provider_execution(worker_id="ambiguous") is True
        ambiguous_detail = await client.get(f"/api/v1/executions/{ambiguous_id}")
        assert ambiguous_detail.json()["status"] == "AMBIGUOUS"

        recovery = await create_execution(
            client,
            admin_csrf,
            provider_id,
            execution_body(
                capability_id,
                context.job.id,
                approval_id,
                SimulationScenario.SUCCESS,
                max_attempts=2,
            ),
            "execution-recovery",
        )
        recovery_id = UUID(str(recovery["execution"]["id"]))
        async with factory() as session:
            async with session.begin():
                claimed = await ProviderExecutionRepository(session).claim_next(
                    worker_id="dead-provider-worker"
                )
                assert claimed is not None and claimed.order_id == recovery_id
            async with session.begin():
                event = await session.get(OutboxEvent, claimed.outbox_id)
                assert event is not None
                event.locked_at = datetime.now(UTC) - timedelta(minutes=10)
            async with session.begin():
                recovered = await ProviderExecutionRepository(session).recover_stale(
                    timeout_seconds=60
                )
                assert recovered == 1
            recovered_event = await session.get(OutboxEvent, claimed.outbox_id)
            assert recovered_event is not None and recovered_event.status == OutboxStatus.RETRY
            recovered_attempt = await session.get(ExecutionAttempt, claimed.attempt_id)
            assert recovered_attempt is not None
            assert recovered_attempt.status.value == "FAILED"

        pending = await create_execution(
            client,
            admin_csrf,
            provider_id,
            execution_body(
                capability_id,
                context.job.id,
                approval_id,
                SimulationScenario.DELAYED_RESPONSE,
            ),
            "execution-invalidate",
        )
        pending_id = UUID(str(pending["execution"]["id"]))
        technical = await integration_session.get(TechnicalApproval, UUID(approval_id))
        assert technical is not None
        claim = await client.post(
            f"/api/v1/cases/{context.job.id}/claim",
            headers=headers(admin_csrf),
            json={"expected_version": context.job.version},
        )
        assert claim.status_code == 200
        update_case = await client.post(
            f"/api/v1/cases/{context.job.id}/update",
            headers=headers(admin_csrf),
            json={"expected_version": context.job.version, "category": "changed-after-gate"},
        )
        assert update_case.status_code == 200
        await integration_session.refresh(technical)
        pending_order = await integration_session.get(ExecutionOrder, pending_id)
        assert technical.status == TechnicalApprovalStatus.INVALIDATED
        assert pending_order is not None and pending_order.status == ExecutionStatus.INVALIDATED
        pending_outbox = await integration_session.scalar(
            select(OutboxEvent).where(OutboxEvent.execution_order_id == pending_id)
        )
        assert pending_outbox is not None and pending_outbox.status == OutboxStatus.INVALIDATED

    succeeded = await integration_session.scalar(
        select(func.count(ExecutionOrder.id)).where(
            ExecutionOrder.id.in_([UUID(item) for item in created_ids]),
            ExecutionOrder.status == ExecutionStatus.SUCCEEDED,
        )
    )
    assert succeeded == 2
