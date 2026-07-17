"""Signed, replay-safe callback intake foundation."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.application.errors import (
    CallbackReplayError,
    CallbackValidationError,
    ProviderNotFoundError,
)
from mediaos.application.provider_contract import mask_secrets
from mediaos.domain.enums import ActorType, CallbackStatus, ExecutionStatus
from mediaos.domain.models import (
    AuditEvent,
    CallbackReceipt,
    ExecutionOrder,
    ProviderConfiguration,
    ProviderFeatureFlags,
    ProviderResponse,
    SecretReference,
    SignatureProfile,
)
from mediaos.infrastructure.secret_resolver import EnvironmentSecretResolver
from mediaos.infrastructure.simulation_provider import get_provider_adapter

CALLBACK_ACTOR_ID = UUID("00000000-0000-0000-0000-000000000004")
MAX_CALLBACK_BYTES = 64 * 1024


class CallbackService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def accept(
        self,
        *,
        provider_id: UUID,
        event_id: str,
        correlation_id: UUID,
        timestamp: str,
        signature: str,
        raw_body: bytes,
    ) -> CallbackReceipt:
        if len(raw_body) > MAX_CALLBACK_BYTES:
            raise CallbackValidationError("Callback payload exceeds the safe storage limit")
        provider = await self.session.get(ProviderConfiguration, provider_id)
        if provider is None or provider.tenant_id is None:
            raise ProviderNotFoundError("Callback provider was not found")
        flags = await self.session.scalar(
            select(ProviderFeatureFlags).where(
                ProviderFeatureFlags.tenant_id == provider.tenant_id
            )
        )
        if (
            flags is None
            or not flags.global_integration_enabled
            or not flags.callback_intake_enabled
            or not provider.callback_enabled
        ):
            raise CallbackValidationError("Callback intake is disabled")
        duplicate = await self.session.scalar(
            select(CallbackReceipt.id).where(
                CallbackReceipt.provider_configuration_id == provider.id,
                CallbackReceipt.event_id == event_id,
            )
        )
        if duplicate is not None:
            raise CallbackReplayError("Callback event was already received")
        if provider.signature_profile_id is None:
            raise CallbackValidationError("Provider has no signature profile")
        profile = await self.session.get(SignatureProfile, provider.signature_profile_id)
        if profile is None:
            raise CallbackValidationError("Provider signature profile is missing")
        reference = await self.session.get(SecretReference, profile.secret_reference_id)
        if reference is None:
            raise CallbackValidationError("Provider signature secret reference is missing")
        try:
            timestamp_value = int(timestamp)
            provider_timestamp = datetime.fromtimestamp(timestamp_value, tz=UTC)
        except (OverflowError, ValueError) as exc:
            raise CallbackValidationError("Callback timestamp is invalid") from exc
        age = abs((datetime.now(UTC) - provider_timestamp).total_seconds())
        if age > profile.timestamp_tolerance_seconds:
            raise CallbackValidationError("Callback timestamp is outside the accepted window")
        secret = EnvironmentSecretResolver().resolve(reference)
        signed = timestamp.encode() + b"." + raw_body
        expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise CallbackValidationError("Callback signature is invalid")
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise CallbackValidationError("Callback payload is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise CallbackValidationError("Callback payload must be a JSON object")
        order = await self.session.scalar(
            select(ExecutionOrder)
            .where(
                ExecutionOrder.correlation_id == correlation_id,
                ExecutionOrder.provider_configuration_id == provider.id,
                ExecutionOrder.tenant_id == provider.tenant_id,
            )
            .with_for_update()
        )
        if order is None:
            raise CallbackValidationError("Callback correlation ID is unknown")
        normalized = get_provider_adapter(provider.provider_type).normalize_response(payload)
        receipt = CallbackReceipt(
            tenant_id=provider.tenant_id,
            provider_configuration_id=provider.id,
            event_id=event_id,
            correlation_id=correlation_id,
            provider_timestamp=provider_timestamp,
            payload_hash=hashlib.sha256(raw_body).hexdigest(),
            raw_payload=mask_secrets(payload),
            normalized_response=normalized.payload,
            signature_valid=True,
            status=CallbackStatus.ACCEPTED,
        )
        self.session.add(receipt)
        self.session.add(
            ProviderResponse(
                execution_order_id=order.id,
                provider_status=normalized.provider_status,
                normalized_status=normalized.normalized_status,
                payload=normalized.payload,
            )
        )
        await self.session.flush()
        if normalized.normalized_status == "SUCCEEDED":
            order.status = ExecutionStatus.SUCCEEDED
            order.completed_at = datetime.now(UTC)
        elif normalized.normalized_status == "AMBIGUOUS":
            order.status = ExecutionStatus.AMBIGUOUS
        self.session.add(
            AuditEvent(
                tenant_id=provider.tenant_id,
                job_id=order.job_id,
                actor_id=CALLBACK_ACTOR_ID,
                actor_type=ActorType.SYSTEM,
                event_type="PROVIDER_CALLBACK_ACCEPTED",
                payload={
                    "callback_receipt_id": str(receipt.id),
                    "execution_order_id": str(order.id),
                    "event_id": event_id,
                    "normalized_status": normalized.normalized_status,
                },
            )
        )
        await self.session.flush()
        return receipt
