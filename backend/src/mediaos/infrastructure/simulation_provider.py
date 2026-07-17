"""Local provider adapter exercising the real adapter contract without external effects."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from mediaos.application.provider_contract import (
    PreparedProviderRequest,
    ProviderExecutionError,
    ProviderExecutionResult,
    mask_secrets,
)
from mediaos.domain.enums import ProviderErrorClassification, SimulationScenario


class SimulationProvider:
    provider_type = "SIMULATION"

    def __init__(self) -> None:
        self._results: dict[UUID, ProviderExecutionResult] = {}

    def validate_configuration(self, configuration: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if configuration.get("provider_type") != self.provider_type:
            errors.append("provider_type must be SIMULATION")
        if configuration.get("production_enabled"):
            errors.append("simulation provider cannot enable production execution")
        return errors

    def validate_request(self, operation: str, payload: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if not operation.strip():
            errors.append("operation is required")
        try:
            SimulationScenario(str(payload.get("simulation_scenario", "SUCCESS")))
        except ValueError:
            errors.append("simulation_scenario is invalid")
        if not isinstance(payload.get("case"), dict):
            errors.append("case payload is required")
        return errors

    def prepare(
        self, correlation_id: UUID, operation: str, payload: dict[str, Any]
    ) -> PreparedProviderRequest:
        return PreparedProviderRequest(
            correlation_id=correlation_id,
            operation=operation,
            payload=mask_secrets(payload),
        )

    async def execute(self, request: PreparedProviderRequest) -> ProviderExecutionResult:
        scenario = SimulationScenario(
            str(request.payload.get("simulation_scenario", SimulationScenario.SUCCESS.value))
        )
        if scenario == SimulationScenario.DELAYED_RESPONSE:
            await asyncio.sleep(0.05)
        error_map = {
            SimulationScenario.TEMPORARY_ERROR: ProviderErrorClassification.TEMPORARY,
            SimulationScenario.PERMANENT_ERROR: ProviderErrorClassification.PERMANENT,
            SimulationScenario.TIMEOUT: ProviderErrorClassification.TIMEOUT,
            SimulationScenario.RATE_LIMIT: ProviderErrorClassification.RATE_LIMIT,
            SimulationScenario.INVALID_SIGNATURE: ProviderErrorClassification.INVALID_SIGNATURE,
            SimulationScenario.INVALID_RESPONSE: ProviderErrorClassification.INVALID_RESPONSE,
        }
        classification = error_map.get(scenario)
        if classification is not None:
            raise ProviderExecutionError(
                f"simulated {scenario.value.lower().replace('_', ' ')}", classification
            )
        if scenario == SimulationScenario.AMBIGUOUS_STATUS:
            result = ProviderExecutionResult(
                provider_status="UNKNOWN",
                normalized_status="AMBIGUOUS",
                payload={"scenario": scenario.value, "confirmed": False},
            )
        else:
            result = ProviderExecutionResult(
                provider_status="PROCESSED",
                normalized_status="SUCCEEDED",
                payload={
                    "scenario": scenario.value,
                    "duplicate_responses": 2
                    if scenario == SimulationScenario.DUPLICATE_RESPONSE
                    else 1,
                    "already_processed": scenario == SimulationScenario.ALREADY_PROCESSED,
                    "external_effect": False,
                },
                external_reference=f"simulation:{request.correlation_id}",
            )
        self._results[request.correlation_id] = result
        return result

    async def query_status(self, correlation_id: UUID) -> ProviderExecutionResult:
        return self._results.get(
            correlation_id,
            ProviderExecutionResult(
                provider_status="UNKNOWN",
                normalized_status="AMBIGUOUS",
                payload={"confirmed": False, "external_effect": False},
            ),
        )

    async def cancel(self, correlation_id: UUID) -> ProviderExecutionResult:
        return ProviderExecutionResult(
            provider_status="CANCEL_UNSUPPORTED",
            normalized_status="AMBIGUOUS",
            payload={"correlation_id": str(correlation_id), "supported": False},
        )

    def normalize_response(self, response: dict[str, Any]) -> ProviderExecutionResult:
        provider_status = str(response.get("status", "UNKNOWN"))
        normalized = (
            "SUCCEEDED"
            if provider_status in {"PROCESSED", "ALREADY_PROCESSED"}
            else "AMBIGUOUS"
        )
        return ProviderExecutionResult(
            provider_status=provider_status,
            normalized_status=normalized,
            payload=mask_secrets(response),
        )

    def classify_error(self, error: Exception) -> ProviderErrorClassification:
        if isinstance(error, ProviderExecutionError):
            return error.classification
        return ProviderErrorClassification.PERMANENT

    async def healthcheck(self) -> dict[str, Any]:
        return {"status": "ready", "external_effect": False}


def get_provider_adapter(provider_type: str) -> SimulationProvider:
    if provider_type != SimulationProvider.provider_type:
        raise ValueError(f"Unsupported provider type: {provider_type}")
    return SimulationProvider()
