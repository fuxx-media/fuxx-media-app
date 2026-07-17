"""Transactional outbox claiming and execution result persistence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.application.provider_contract import ProviderExecutionResult
from mediaos.domain.enums import (
    ActorType,
    ExecutionAttemptStatus,
    ExecutionStatus,
    OutboxStatus,
    ProviderErrorClassification,
    RetryPlanStatus,
)
from mediaos.domain.models import (
    AuditEvent,
    ExecutionAttempt,
    ExecutionOrder,
    OutboxEvent,
    ProviderConfiguration,
    ProviderResponse,
    ResultArtifact,
    RetryPlan,
)

WORKER_ACTOR_ID = UUID("00000000-0000-0000-0000-000000000003")
RETRYABLE = {
    ProviderErrorClassification.TEMPORARY,
    ProviderErrorClassification.TIMEOUT,
    ProviderErrorClassification.RATE_LIMIT,
}


@dataclass(frozen=True, slots=True)
class ClaimedExecution:
    outbox_id: UUID
    order_id: UUID
    attempt_id: UUID
    provider_type: str
    correlation_id: UUID
    operation: str
    prepared_payload: dict[str, object]


class ProviderExecutionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def recover_stale(self, *, timeout_seconds: int = 300) -> int:
        cutoff = datetime.now(UTC) - timedelta(seconds=timeout_seconds)
        events = list(
            (
                await self.session.scalars(
                    select(OutboxEvent)
                    .where(
                        OutboxEvent.status == OutboxStatus.CLAIMED,
                        OutboxEvent.locked_at < cutoff,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for event in events:
            order = await self.session.get(ExecutionOrder, event.execution_order_id)
            attempt = await self.session.scalar(
                select(ExecutionAttempt)
                .where(
                    ExecutionAttempt.outbox_event_id == event.id,
                    ExecutionAttempt.status == ExecutionAttemptStatus.RUNNING,
                )
                .order_by(ExecutionAttempt.attempt_number.desc())
                .limit(1)
            )
            if attempt is not None:
                attempt.status = ExecutionAttemptStatus.FAILED
                attempt.error_message = "provider worker claim expired before completion"
                attempt.error_classification = ProviderErrorClassification.TEMPORARY
                attempt.completed_at = datetime.now(UTC)
            if event.attempts >= event.max_attempts:
                event.status = OutboxStatus.DEAD_LETTER
                if order is not None:
                    order.status = ExecutionStatus.DEAD_LETTER
                    order.completed_at = datetime.now(UTC)
            else:
                event.status = OutboxStatus.RETRY
                event.available_at = datetime.now(UTC)
                if order is not None:
                    order.status = ExecutionStatus.RETRY
            event.last_error = "provider worker claim expired before completion"
            event.locked_at = None
            event.locked_by = None
            if order is not None:
                self._audit(
                    order,
                    "PROVIDER_EXECUTION_STALE_CLAIM_RECOVERED",
                    {"terminal": event.status == OutboxStatus.DEAD_LETTER},
                )
        return len(events)

    async def claim_next(self, *, worker_id: str) -> ClaimedExecution | None:
        now = datetime.now(UTC)
        event = await self.session.scalar(
            select(OutboxEvent)
            .where(
                OutboxEvent.status.in_([OutboxStatus.PENDING, OutboxStatus.RETRY]),
                OutboxEvent.available_at <= now,
                OutboxEvent.attempts < OutboxEvent.max_attempts,
            )
            .order_by(OutboxEvent.available_at, OutboxEvent.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if event is None:
            return None
        order = await self.session.scalar(
            select(ExecutionOrder)
            .where(ExecutionOrder.id == event.execution_order_id)
            .with_for_update()
        )
        if order is None:
            raise RuntimeError("Outbox references a missing execution order")
        if order.status in {
            ExecutionStatus.INVALIDATED,
            ExecutionStatus.DISCARDED,
            ExecutionStatus.SUCCEEDED,
        }:
            event.status = OutboxStatus.INVALIDATED
            return None
        provider = await self.session.get(
            ProviderConfiguration, order.provider_configuration_id
        )
        if provider is None:
            raise RuntimeError("Execution references a missing provider configuration")
        attempt_number = int(
            await self.session.scalar(
                select(func.coalesce(func.max(ExecutionAttempt.attempt_number), 0)).where(
                    ExecutionAttempt.execution_order_id == order.id
                )
            )
            or 0
        ) + 1
        event.status = OutboxStatus.CLAIMED
        event.attempts += 1
        event.locked_at = now
        event.locked_by = worker_id
        order.status = ExecutionStatus.RUNNING
        order.started_at = order.started_at or now
        attempt = ExecutionAttempt(
            execution_order_id=order.id,
            outbox_event_id=event.id,
            attempt_number=attempt_number,
            worker_id=worker_id,
            status=ExecutionAttemptStatus.RUNNING,
            request_payload=order.prepared_payload,
        )
        self.session.add(attempt)
        await self.session.flush()
        return ClaimedExecution(
            outbox_id=event.id,
            order_id=order.id,
            attempt_id=attempt.id,
            provider_type=provider.provider_type,
            correlation_id=order.correlation_id,
            operation=order.operation,
            prepared_payload=order.prepared_payload,
        )

    async def succeed(
        self, claimed: ClaimedExecution, result: ProviderExecutionResult
    ) -> None:
        now = datetime.now(UTC)
        order, event, attempt = await self._locked(claimed)
        if result.normalized_status == "AMBIGUOUS":
            order.status = ExecutionStatus.AMBIGUOUS
            event.status = OutboxStatus.DEAD_LETTER
            attempt.status = ExecutionAttemptStatus.AMBIGUOUS
        else:
            order.status = ExecutionStatus.SUCCEEDED
            order.completed_at = now
            event.status = OutboxStatus.PROCESSED
            attempt.status = ExecutionAttemptStatus.SUCCEEDED
        event.locked_at = None
        event.locked_by = None
        attempt.response_payload = result.payload
        attempt.completed_at = now
        self.session.add(
            ProviderResponse(
                execution_order_id=order.id,
                execution_attempt_id=attempt.id,
                provider_status=result.provider_status,
                normalized_status=result.normalized_status,
                payload=result.payload,
            )
        )
        serialized = json.dumps(result.payload, sort_keys=True, separators=(",", ":"))
        self.session.add(
            ResultArtifact(
                execution_order_id=order.id,
                execution_attempt_id=attempt.id,
                kind="NORMALIZED_PROVIDER_RESULT",
                sha256=hashlib.sha256(serialized.encode()).hexdigest(),
                metadata_json={"external_reference": result.external_reference},
            )
        )
        self._audit(
            order,
            "PROVIDER_EXECUTION_AMBIGUOUS"
            if result.normalized_status == "AMBIGUOUS"
            else "PROVIDER_EXECUTION_SUCCEEDED",
            {"attempt": attempt.attempt_number, "external_effect": False},
        )

    async def fail(
        self,
        claimed: ClaimedExecution,
        *,
        message: str,
        classification: ProviderErrorClassification,
    ) -> None:
        now = datetime.now(UTC)
        order, event, attempt = await self._locked(claimed)
        attempt.status = ExecutionAttemptStatus.FAILED
        attempt.error_message = message
        attempt.error_classification = classification
        attempt.completed_at = now
        event.last_error = message
        event.locked_at = None
        event.locked_by = None
        if classification in RETRYABLE and event.attempts < event.max_attempts:
            configured = order.request_payload.get("retry_backoff_seconds", 1)
            base = int(configured) if isinstance(configured, int | float | str) else 1
            backoff = min(max(base, 0) * (2 ** (event.attempts - 1)), 300)
            scheduled_for = now + timedelta(seconds=backoff)
            order.status = ExecutionStatus.RETRY
            order.next_attempt_at = scheduled_for
            event.status = OutboxStatus.RETRY
            event.available_at = scheduled_for
            self.session.add(
                RetryPlan(
                    execution_order_id=order.id,
                    attempt_number=attempt.attempt_number,
                    scheduled_for=scheduled_for,
                    backoff_seconds=backoff,
                    classification=classification,
                    status=RetryPlanStatus.SCHEDULED,
                )
            )
            event_type = "PROVIDER_EXECUTION_RETRY_SCHEDULED"
        else:
            order.status = ExecutionStatus.DEAD_LETTER
            order.completed_at = now
            event.status = OutboxStatus.DEAD_LETTER
            event_type = "PROVIDER_EXECUTION_DEAD_LETTER"
        self._audit(
            order,
            event_type,
            {
                "attempt": attempt.attempt_number,
                "classification": classification.value,
                "external_effect": False,
            },
        )

    async def _locked(
        self, claimed: ClaimedExecution
    ) -> tuple[ExecutionOrder, OutboxEvent, ExecutionAttempt]:
        order = await self.session.scalar(
            select(ExecutionOrder).where(ExecutionOrder.id == claimed.order_id).with_for_update()
        )
        event = await self.session.scalar(
            select(OutboxEvent).where(OutboxEvent.id == claimed.outbox_id).with_for_update()
        )
        attempt = await self.session.scalar(
            select(ExecutionAttempt)
            .where(ExecutionAttempt.id == claimed.attempt_id)
            .with_for_update()
        )
        if order is None or event is None or attempt is None:
            raise RuntimeError("Claimed execution state is incomplete")
        return order, event, attempt

    def _audit(
        self, order: ExecutionOrder, event_type: str, payload: dict[str, object]
    ) -> None:
        self.session.add(
            AuditEvent(
                tenant_id=order.tenant_id,
                job_id=order.job_id,
                actor_id=WORKER_ACTOR_ID,
                actor_type=ActorType.WORKER,
                event_type=event_type,
                payload={"execution_order_id": str(order.id), **payload},
            )
        )
