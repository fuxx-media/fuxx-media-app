"""Revision-gated provider configuration, dry-run, approval, and outbox service."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.application.errors import (
    ApprovalConflictError,
    AuthorizationError,
    ExecutionNotFoundError,
    IdempotencyConflictError,
    JobNotFoundError,
    ProviderNotFoundError,
    ProviderValidationError,
    TenantBoundaryError,
)
from mediaos.application.provider_contract import mask_secrets
from mediaos.domain.actor import Actor
from mediaos.domain.enums import (
    ActorType,
    ApprovalStatus,
    ExecutionStatus,
    OutboxStatus,
    RoleName,
    SimulationScenario,
    TechnicalApprovalStatus,
)
from mediaos.domain.models import (
    ApprovalRequest,
    AuditEvent,
    ContentJob,
    DryRunResult,
    ExecutionAttempt,
    ExecutionOrder,
    ExecutionRevision,
    OutboxEvent,
    ProviderCapability,
    ProviderConfiguration,
    ProviderFeatureFlags,
    ProviderResponse,
    ResultArtifact,
    RetryPlan,
    SecretReference,
    SignatureProfile,
    SimulationScenarioConfiguration,
    TechnicalApproval,
)
from mediaos.infrastructure.simulation_provider import get_provider_adapter


@dataclass(frozen=True, slots=True)
class CreatedExecution:
    order: ExecutionOrder
    replayed: bool
    validation_errors: list[str]


class ProviderService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def configure_simulation_provider(
        self,
        *,
        actor: Actor,
        name: str,
        secret_reference_name: str,
        secret_environment_variable: str,
        signature_profile_name: str,
        capability_operation: str,
    ) -> ProviderConfiguration:
        self._require_admin(actor)
        tenant_id = self._tenant(actor)
        if not secret_environment_variable.startswith("MEDIAOS_"):
            raise ProviderValidationError("Secret environment reference must start with MEDIAOS_")
        flags = await self.session.scalar(
            select(ProviderFeatureFlags).where(ProviderFeatureFlags.tenant_id == tenant_id)
        )
        if flags is None:
            self.session.add(ProviderFeatureFlags(tenant_id=tenant_id))
        secret = await self.session.scalar(
            select(SecretReference).where(
                SecretReference.tenant_id == tenant_id,
                SecretReference.name == secret_reference_name,
            )
        )
        if secret is None:
            secret = SecretReference(
                tenant_id=tenant_id,
                name=secret_reference_name,
                environment_variable=secret_environment_variable,
                purpose="Simulation callback signature",
            )
            self.session.add(secret)
            await self.session.flush()
        elif secret.environment_variable != secret_environment_variable:
            raise ProviderValidationError(
                "Secret reference name already targets another environment key"
            )
        signature = await self.session.scalar(
            select(SignatureProfile).where(
                SignatureProfile.tenant_id == tenant_id,
                SignatureProfile.name == signature_profile_name,
            )
        )
        if signature is None:
            signature = SignatureProfile(
                tenant_id=tenant_id,
                name=signature_profile_name,
                secret_reference_id=secret.id,
            )
            self.session.add(signature)
            await self.session.flush()
        provider = await self.session.scalar(
            select(ProviderConfiguration).where(
                ProviderConfiguration.tenant_id == tenant_id,
                ProviderConfiguration.name == name,
            )
        )
        if provider is None:
            provider = ProviderConfiguration(
                tenant_id=tenant_id,
                name=name,
                provider_type="SIMULATION",
                enabled=True,
                settings={"mode": "local", "external_effect": False},
                secret_reference_id=secret.id,
                signature_profile_id=signature.id,
                dry_run_enabled=True,
                production_enabled=False,
                callback_enabled=False,
            )
            self.session.add(provider)
            await self.session.flush()
        else:
            provider.secret_reference_id = secret.id
            provider.signature_profile_id = signature.id
            provider.enabled = True
            provider.dry_run_enabled = True
            provider.production_enabled = False
            provider.callback_enabled = False
        capability = await self.session.scalar(
            select(ProviderCapability).where(
                ProviderCapability.provider_configuration_id == provider.id,
                ProviderCapability.operation == capability_operation,
            )
        )
        if capability is None:
            self.session.add(
                ProviderCapability(
                    provider_configuration_id=provider.id,
                    name="Lokale Vorgangssimulation",
                    operation=capability_operation,
                    required_fields=["title", "category"],
                )
            )
        existing_scenarios = set(
            (
                await self.session.scalars(
                    select(SimulationScenarioConfiguration.scenario).where(
                        SimulationScenarioConfiguration.provider_configuration_id == provider.id
                    )
                )
            ).all()
        )
        for scenario in SimulationScenario:
            if scenario not in existing_scenarios:
                self.session.add(
                    SimulationScenarioConfiguration(
                        provider_configuration_id=provider.id,
                        name=scenario.value.lower(),
                        scenario=scenario,
                        settings={"external_effect": False},
                    )
                )
        self._audit(
            tenant_id,
            actor,
            "SIMULATION_PROVIDER_CONFIGURED",
            None,
            {
                "provider_configuration_id": str(provider.id),
                "secret_reference": secret.name,
                "production_enabled": False,
                "callback_enabled": False,
            },
        )
        return provider

    async def list_providers(self, *, actor: Actor) -> list[dict[str, Any]]:
        tenant_id = self._tenant(actor)
        providers = list(
            (
                await self.session.scalars(
                    select(ProviderConfiguration)
                    .where(ProviderConfiguration.tenant_id == tenant_id)
                    .order_by(ProviderConfiguration.name)
                )
            ).all()
        )
        return [await self.provider_dict(provider) for provider in providers]

    async def provider_dict(self, provider: ProviderConfiguration) -> dict[str, Any]:
        capabilities = list(
            (
                await self.session.scalars(
                    select(ProviderCapability)
                    .where(ProviderCapability.provider_configuration_id == provider.id)
                    .order_by(ProviderCapability.operation)
                )
            ).all()
        )
        secret = (
            await self.session.get(SecretReference, provider.secret_reference_id)
            if provider.secret_reference_id
            else None
        )
        signature = (
            await self.session.get(SignatureProfile, provider.signature_profile_id)
            if provider.signature_profile_id
            else None
        )
        return {
            "id": str(provider.id),
            "name": provider.name,
            "provider_type": provider.provider_type,
            "enabled": provider.enabled,
            "settings": mask_secrets(provider.settings),
            "dry_run_enabled": provider.dry_run_enabled,
            "production_enabled": provider.production_enabled,
            "callback_enabled": provider.callback_enabled,
            "secret_reference": (
                {
                    "id": str(secret.id),
                    "name": secret.name,
                    "environment_variable": secret.environment_variable,
                    "configured": secret.active,
                }
                if secret
                else None
            ),
            "signature_profile": (
                {
                    "id": str(signature.id),
                    "name": signature.name,
                    "algorithm": signature.algorithm,
                    "timestamp_tolerance_seconds": signature.timestamp_tolerance_seconds,
                }
                if signature
                else None
            ),
            "capabilities": [
                {
                    "id": str(capability.id),
                    "name": capability.name,
                    "operation": capability.operation,
                    "required_fields": capability.required_fields,
                    "enabled": capability.enabled,
                }
                for capability in capabilities
            ],
        }

    async def feature_flags(self, *, actor: Actor) -> dict[str, bool]:
        tenant_id = self._tenant(actor)
        flags = await self.session.scalar(
            select(ProviderFeatureFlags).where(ProviderFeatureFlags.tenant_id == tenant_id)
        )
        return {
            "global_integration_enabled": flags.global_integration_enabled if flags else True,
            "dry_run_enabled": flags.dry_run_enabled if flags else True,
            "production_execution_enabled": (
                flags.production_execution_enabled if flags else False
            ),
            "callback_intake_enabled": flags.callback_intake_enabled if flags else False,
        }

    async def approve_technical_execution(
        self,
        *,
        actor: Actor,
        provider_id: UUID,
        capability_id: UUID,
        job_id: UUID,
        reason: str,
    ) -> TechnicalApproval:
        self._require_admin(actor)
        tenant_id = self._tenant(actor)
        job = await self._job(tenant_id, job_id)
        provider, capability = await self._provider_capability(
            tenant_id, provider_id, capability_id
        )
        business = await self._business_approval(job)
        approval = TechnicalApproval(
            tenant_id=tenant_id,
            job_id=job.id,
            job_revision=job.version,
            provider_configuration_id=provider.id,
            capability_id=capability.id,
            approved_by=actor.id,
            status=TechnicalApprovalStatus.APPROVED,
            reason=reason.strip(),
        )
        if not approval.reason:
            raise ProviderValidationError("Technical approval requires a reason")
        self.session.add(approval)
        await self.session.flush()
        self._audit(
            tenant_id,
            actor,
            "TECHNICAL_EXECUTION_APPROVED",
            job.id,
            {
                "technical_approval_id": str(approval.id),
                "business_approval_id": str(business.id),
                "job_revision": job.version,
            },
        )
        return approval

    async def create_dry_run(
        self,
        *,
        actor: Actor,
        provider_id: UUID,
        capability_id: UUID,
        job_id: UUID,
        operation: str,
        scenario: SimulationScenario,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> CreatedExecution:
        if actor.roles.isdisjoint({RoleName.ADMIN, RoleName.BACKOFFICE}):
            raise AuthorizationError("Admin or Backoffice role is required for dry runs")
        return await self._create_order(
            actor=actor,
            provider_id=provider_id,
            capability_id=capability_id,
            job_id=job_id,
            operation=operation,
            scenario=scenario,
            idempotency_key=idempotency_key,
            payload=payload,
            dry_run=True,
            technical_approval_id=None,
        )

    async def create_execution(
        self,
        *,
        actor: Actor,
        provider_id: UUID,
        capability_id: UUID,
        job_id: UUID,
        operation: str,
        scenario: SimulationScenario,
        technical_approval_id: UUID,
        idempotency_key: str,
        payload: dict[str, Any],
        max_attempts: int,
        retry_backoff_seconds: int,
    ) -> CreatedExecution:
        if actor.roles.isdisjoint({RoleName.ADMIN, RoleName.BACKOFFICE}):
            raise AuthorizationError("Admin or Backoffice role is required")
        return await self._create_order(
            actor=actor,
            provider_id=provider_id,
            capability_id=capability_id,
            job_id=job_id,
            operation=operation,
            scenario=scenario,
            idempotency_key=idempotency_key,
            payload={
                **payload,
                "max_attempts": max_attempts,
                "retry_backoff_seconds": retry_backoff_seconds,
            },
            dry_run=False,
            technical_approval_id=technical_approval_id,
        )

    async def _create_order(
        self,
        *,
        actor: Actor,
        provider_id: UUID,
        capability_id: UUID,
        job_id: UUID,
        operation: str,
        scenario: SimulationScenario,
        idempotency_key: str,
        payload: dict[str, Any],
        dry_run: bool,
        technical_approval_id: UUID | None,
    ) -> CreatedExecution:
        tenant_id = self._tenant(actor)
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": f"provider:{tenant_id}:{idempotency_key}"},
        )
        job = await self._job(tenant_id, job_id)
        provider, capability = await self._provider_capability(
            tenant_id, provider_id, capability_id
        )
        if capability.operation != operation:
            raise ProviderValidationError("Provider capability does not support the operation")
        flags = await self.session.scalar(
            select(ProviderFeatureFlags).where(ProviderFeatureFlags.tenant_id == tenant_id)
        )
        if flags is None or not flags.global_integration_enabled:
            raise ProviderValidationError("Global provider integration is disabled")
        if dry_run and (not flags.dry_run_enabled or not provider.dry_run_enabled):
            raise ProviderValidationError("Dry-run is disabled")
        if provider.provider_type != "SIMULATION" and (
            not flags.production_execution_enabled or not provider.production_enabled
        ):
            raise ProviderValidationError("Productive execution is disabled")
        if not provider.enabled:
            raise ProviderValidationError("Provider is disabled")
        if provider.secret_reference_id is None:
            raise ProviderValidationError("Provider has no secret reference")
        secret = await self.session.get(SecretReference, provider.secret_reference_id)
        if secret is None or not secret.active:
            raise ProviderValidationError("Provider secret reference is missing or inactive")
        business = await self._business_approval(job)
        technical: TechnicalApproval | None = None
        if not dry_run:
            if technical_approval_id is None:
                raise ProviderValidationError("Technical approval is required")
            technical = await self.session.scalar(
                select(TechnicalApproval).where(
                    TechnicalApproval.id == technical_approval_id,
                    TechnicalApproval.tenant_id == tenant_id,
                    TechnicalApproval.job_id == job.id,
                    TechnicalApproval.job_revision == job.version,
                    TechnicalApproval.provider_configuration_id == provider.id,
                    TechnicalApproval.capability_id == capability.id,
                    TechnicalApproval.status == TechnicalApprovalStatus.APPROVED,
                    TechnicalApproval.invalidated_at.is_(None),
                )
            )
            if technical is None:
                raise ProviderValidationError("Technical approval is stale or invalid")
        case_payload: dict[str, Any] = {
            "id": str(job.id),
            "revision": job.version,
            "title": job.title,
            "category": job.category,
            "priority": job.priority.value,
            "business_status": job.business_status.value,
        }
        request_payload = {
            "case": case_payload,
            "simulation_scenario": scenario.value,
            **mask_secrets(payload),
        }
        adapter = get_provider_adapter(provider.provider_type)
        configuration_errors = adapter.validate_configuration(
            {
                "provider_type": provider.provider_type,
                "production_enabled": provider.production_enabled,
                **provider.settings,
            }
        )
        missing_fields = [
            field for field in capability.required_fields if not case_payload.get(field)
        ]
        validation_errors = [
            *configuration_errors,
            *adapter.validate_request(operation, request_payload),
            *[f"required case field is missing: {field}" for field in missing_fields],
        ]
        correlation_id = uuid4()
        prepared = adapter.prepare(correlation_id, operation, request_payload)
        fingerprint_source = {
            "tenant_id": str(tenant_id),
            "provider_id": str(provider.id),
            "operation": operation,
            "job_id": str(job.id),
            "job_revision": job.version,
            "dry_run": dry_run,
            "payload": prepared.payload,
        }
        request_fingerprint = hashlib.sha256(
            json.dumps(fingerprint_source, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        existing = await self.session.scalar(
            select(ExecutionOrder).where(
                ExecutionOrder.tenant_id == tenant_id,
                or_(
                    ExecutionOrder.idempotency_key == idempotency_key,
                    (
                        (ExecutionOrder.provider_configuration_id == provider.id)
                        & (ExecutionOrder.operation == operation)
                        & (ExecutionOrder.job_id == job.id)
                        & (ExecutionOrder.job_revision == job.version)
                        & (ExecutionOrder.request_fingerprint == request_fingerprint)
                        & (ExecutionOrder.dry_run == dry_run)
                    ),
                ),
            )
        )
        if existing is not None:
            if existing.request_fingerprint != request_fingerprint:
                raise IdempotencyConflictError("Idempotency key was reused with another request")
            dry_result = await self.session.scalar(
                select(DryRunResult).where(DryRunResult.execution_order_id == existing.id)
            )
            return CreatedExecution(
                order=existing,
                replayed=True,
                validation_errors=dry_result.validation_errors if dry_result else [],
            )
        max_attempts_value = payload.get("max_attempts", 3)
        max_attempts = int(max_attempts_value) if not dry_run else 1
        if max_attempts < 1 or max_attempts > 10:
            raise ProviderValidationError("max_attempts must be between 1 and 10")
        status = (
            ExecutionStatus.DRY_RUN_FAILED
            if dry_run and validation_errors
            else ExecutionStatus.DRY_RUN_SUCCEEDED
            if dry_run
            else ExecutionStatus.QUEUED
        )
        if not dry_run and validation_errors:
            raise ProviderValidationError(
                "Provider request validation failed", details={"errors": validation_errors}
            )
        order = ExecutionOrder(
            tenant_id=tenant_id,
            job_id=job.id,
            job_revision=job.version,
            provider_configuration_id=provider.id,
            capability_id=capability.id,
            operation=operation,
            business_approval_id=business.id,
            technical_approval_id=technical.id if technical else None,
            created_by=actor.id,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            request_fingerprint=request_fingerprint,
            request_payload=request_payload,
            prepared_payload=prepared.payload,
            dry_run=dry_run,
            external_effect=False,
            status=status,
            max_attempts=max_attempts,
            completed_at=datetime.now(UTC) if dry_run else None,
        )
        self.session.add(order)
        await self.session.flush()
        self.session.add(
            ExecutionRevision(
                execution_order_id=order.id,
                revision=1,
                snapshot={
                    "job_revision": job.version,
                    "business_approval_id": str(business.id),
                    "technical_approval_id": str(technical.id) if technical else None,
                    "prepared_payload": prepared.payload,
                    "status": status.value,
                },
            )
        )
        if dry_run:
            self.session.add(
                DryRunResult(
                    execution_order_id=order.id,
                    valid=not validation_errors,
                    masked_payload=prepared.payload,
                    validation_errors=validation_errors,
                    external_effect=False,
                )
            )
            event_type = "PROVIDER_DRY_RUN_COMPLETED"
        else:
            self.session.add(
                OutboxEvent(
                    tenant_id=tenant_id,
                    execution_order_id=order.id,
                    event_type="PROVIDER_EXECUTION_REQUESTED",
                    sequence=1,
                    payload={
                        "execution_order_id": str(order.id),
                        "correlation_id": str(order.correlation_id),
                        "job_revision": job.version,
                    },
                    status=OutboxStatus.PENDING,
                    max_attempts=max_attempts,
                )
            )
            event_type = "PROVIDER_EXECUTION_QUEUED"
        self._audit(
            tenant_id,
            actor,
            event_type,
            job.id,
            {
                "execution_order_id": str(order.id),
                "job_revision": job.version,
                "dry_run": dry_run,
                "external_effect": False,
                "validation_errors": validation_errors,
            },
        )
        return CreatedExecution(order=order, replayed=False, validation_errors=validation_errors)

    async def list_executions(self, *, actor: Actor) -> list[dict[str, Any]]:
        tenant_id = self._tenant(actor)
        orders = list(
            (
                await self.session.scalars(
                    select(ExecutionOrder)
                    .where(ExecutionOrder.tenant_id == tenant_id)
                    .order_by(ExecutionOrder.created_at.desc())
                    .limit(100)
                )
            ).all()
        )
        return [await self.execution_dict(order) for order in orders]

    async def execution_detail(self, *, actor: Actor, order_id: UUID) -> dict[str, Any]:
        tenant_id = self._tenant(actor)
        order = await self.session.scalar(
            select(ExecutionOrder).where(
                ExecutionOrder.id == order_id, ExecutionOrder.tenant_id == tenant_id
            )
        )
        if order is None:
            raise ExecutionNotFoundError("Execution order was not found")
        return await self.execution_dict(order, detailed=True)

    async def execution_dict(
        self, order: ExecutionOrder, *, detailed: bool = False
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": str(order.id),
            "job_id": str(order.job_id),
            "job_revision": order.job_revision,
            "provider_configuration_id": str(order.provider_configuration_id),
            "capability_id": str(order.capability_id),
            "operation": order.operation,
            "correlation_id": str(order.correlation_id),
            "status": order.status.value,
            "dry_run": order.dry_run,
            "external_effect": order.external_effect,
            "prepared_payload": order.prepared_payload,
            "max_attempts": order.max_attempts,
            "discard_reason": order.discard_reason,
            "created_at": order.created_at,
            "completed_at": order.completed_at,
        }
        if not detailed:
            return data
        outbox = list(
            (
                await self.session.scalars(
                    select(OutboxEvent)
                    .where(OutboxEvent.execution_order_id == order.id)
                    .order_by(OutboxEvent.sequence)
                )
            ).all()
        )
        attempts = list(
            (
                await self.session.scalars(
                    select(ExecutionAttempt)
                    .where(ExecutionAttempt.execution_order_id == order.id)
                    .order_by(ExecutionAttempt.attempt_number)
                )
            ).all()
        )
        responses = list(
            (
                await self.session.scalars(
                    select(ProviderResponse).where(
                        ProviderResponse.execution_order_id == order.id
                    )
                )
            ).all()
        )
        retries = list(
            (
                await self.session.scalars(
                    select(RetryPlan).where(RetryPlan.execution_order_id == order.id)
                )
            ).all()
        )
        artifacts = list(
            (
                await self.session.scalars(
                    select(ResultArtifact).where(ResultArtifact.execution_order_id == order.id)
                )
            ).all()
        )
        dry_run = await self.session.scalar(
            select(DryRunResult).where(DryRunResult.execution_order_id == order.id)
        )
        audit_events = list(
            (
                await self.session.scalars(
                    select(AuditEvent)
                    .where(
                        AuditEvent.job_id == order.job_id,
                        AuditEvent.event_type.like("%PROVIDER%"),
                    )
                    .order_by(AuditEvent.created_at)
                )
            ).all()
        )
        data.update(
            {
                "outbox": [
                    {
                        "id": str(item.id),
                        "sequence": item.sequence,
                        "status": item.status.value,
                        "attempts": item.attempts,
                        "last_error": item.last_error,
                    }
                    for item in outbox
                ],
                "attempts": [
                    {
                        "id": str(item.id),
                        "attempt_number": item.attempt_number,
                        "status": item.status.value,
                        "error_classification": (
                            item.error_classification.value if item.error_classification else None
                        ),
                        "error_message": item.error_message,
                        "response_payload": item.response_payload,
                    }
                    for item in attempts
                ],
                "responses": [
                    {
                        "provider_status": item.provider_status,
                        "normalized_status": item.normalized_status,
                        "payload": item.payload,
                    }
                    for item in responses
                ],
                "retry_plans": [
                    {
                        "attempt_number": item.attempt_number,
                        "backoff_seconds": item.backoff_seconds,
                        "classification": item.classification.value,
                        "status": item.status.value,
                    }
                    for item in retries
                ],
                "artifacts": [
                    {"kind": item.kind, "sha256": item.sha256, "metadata": item.metadata_json}
                    for item in artifacts
                ],
                "dry_run_result": (
                    {
                        "valid": dry_run.valid,
                        "masked_payload": dry_run.masked_payload,
                        "validation_errors": dry_run.validation_errors,
                        "external_effect": dry_run.external_effect,
                    }
                    if dry_run
                    else None
                ),
                "audit_events": [
                    {
                        "id": str(item.id),
                        "event_type": item.event_type,
                        "payload": item.payload,
                        "created_at": item.created_at,
                    }
                    for item in audit_events
                ],
            }
        )
        return data

    async def resume_execution(
        self, *, actor: Actor, order_id: UUID, reason: str
    ) -> ExecutionOrder:
        self._require_admin(actor)
        tenant_id = self._tenant(actor)
        order = await self.session.scalar(
            select(ExecutionOrder)
            .where(ExecutionOrder.id == order_id, ExecutionOrder.tenant_id == tenant_id)
            .with_for_update()
        )
        if order is None:
            raise ExecutionNotFoundError("Execution order was not found")
        if order.status not in {ExecutionStatus.DEAD_LETTER, ExecutionStatus.AMBIGUOUS}:
            raise ProviderValidationError("Only permanent or ambiguous failures can be resumed")
        reason = reason.strip()
        if not reason:
            raise ProviderValidationError("Manual resume requires a reason")
        sequence = int(
            await self.session.scalar(
                select(func.coalesce(func.max(OutboxEvent.sequence), 0)).where(
                    OutboxEvent.execution_order_id == order.id
                )
            )
            or 0
        ) + 1
        order.status = ExecutionStatus.QUEUED
        order.completed_at = None
        order.next_attempt_at = None
        self.session.add(
            OutboxEvent(
                tenant_id=tenant_id,
                execution_order_id=order.id,
                event_type="PROVIDER_EXECUTION_MANUALLY_RESUMED",
                sequence=sequence,
                payload={"reason": reason, "external_effect": False},
                max_attempts=order.max_attempts,
            )
        )
        self._audit(
            tenant_id,
            actor,
            "PROVIDER_EXECUTION_MANUALLY_RESUMED",
            order.job_id,
            {"execution_order_id": str(order.id), "reason": reason},
        )
        return order

    async def discard_execution(
        self, *, actor: Actor, order_id: UUID, reason: str
    ) -> ExecutionOrder:
        self._require_admin(actor)
        tenant_id = self._tenant(actor)
        order = await self.session.scalar(
            select(ExecutionOrder)
            .where(ExecutionOrder.id == order_id, ExecutionOrder.tenant_id == tenant_id)
            .with_for_update()
        )
        if order is None:
            raise ExecutionNotFoundError("Execution order was not found")
        reason = reason.strip()
        if not reason:
            raise ProviderValidationError("Discarding an execution requires a reason")
        if order.status == ExecutionStatus.SUCCEEDED:
            raise ProviderValidationError("Successful execution evidence cannot be discarded")
        order.status = ExecutionStatus.DISCARDED
        order.discard_reason = reason
        order.completed_at = datetime.now(UTC)
        await self.session.execute(
            update(OutboxEvent)
            .where(
                OutboxEvent.execution_order_id == order.id,
                OutboxEvent.status.in_([OutboxStatus.PENDING, OutboxStatus.RETRY]),
            )
            .values(status=OutboxStatus.INVALIDATED)
        )
        self._audit(
            tenant_id,
            actor,
            "PROVIDER_EXECUTION_DISCARDED",
            order.job_id,
            {"execution_order_id": str(order.id), "reason": reason},
        )
        return order

    async def _provider_capability(
        self, tenant_id: UUID, provider_id: UUID, capability_id: UUID
    ) -> tuple[ProviderConfiguration, ProviderCapability]:
        row = (
            await self.session.execute(
                select(ProviderConfiguration, ProviderCapability)
                .join(
                    ProviderCapability,
                    ProviderCapability.provider_configuration_id == ProviderConfiguration.id,
                )
                .where(
                    ProviderConfiguration.id == provider_id,
                    ProviderConfiguration.tenant_id == tenant_id,
                    ProviderCapability.id == capability_id,
                    ProviderCapability.enabled.is_(True),
                )
            )
        ).one_or_none()
        if row is None:
            raise ProviderNotFoundError("Provider capability was not found in the tenant")
        return row[0], row[1]

    async def _job(self, tenant_id: UUID, job_id: UUID) -> ContentJob:
        job = await self.session.scalar(
            select(ContentJob).where(
                ContentJob.id == job_id, ContentJob.tenant_id == tenant_id
            )
        )
        if job is None:
            raise JobNotFoundError("Case was not found in the authenticated tenant")
        return job

    async def _business_approval(self, job: ContentJob) -> ApprovalRequest:
        approval = await self.session.scalar(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.job_id == job.id,
                ApprovalRequest.job_revision == job.version,
                ApprovalRequest.status == ApprovalStatus.APPROVED,
                ApprovalRequest.invalidated_at.is_(None),
            )
            .order_by(ApprovalRequest.resolved_at.desc())
            .limit(1)
        )
        if approval is None:
            raise ApprovalConflictError("Current case revision has no valid business approval")
        return approval

    @staticmethod
    def _require_admin(actor: Actor) -> None:
        if actor.type != ActorType.USER or RoleName.ADMIN not in actor.roles:
            raise AuthorizationError("Admin role is required")

    @staticmethod
    def _tenant(actor: Actor) -> UUID:
        if actor.tenant_id is None:
            raise TenantBoundaryError("Authenticated actor has no tenant")
        return actor.tenant_id

    def _audit(
        self,
        tenant_id: UUID,
        actor: Actor,
        event_type: str,
        job_id: UUID | None,
        payload: dict[str, Any],
    ) -> None:
        self.session.add(
            AuditEvent(
                tenant_id=tenant_id,
                job_id=job_id,
                actor_id=actor.id,
                actor_type=actor.type,
                event_type=event_type,
                payload=payload,
            )
        )
