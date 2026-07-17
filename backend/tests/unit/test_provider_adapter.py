"""Provider adapter contract, simulation scenarios, and masking tests."""

from uuid import uuid4

import pytest

from mediaos.application.provider_contract import ProviderExecutionError, mask_secrets
from mediaos.domain.enums import ProviderErrorClassification, SimulationScenario
from mediaos.infrastructure.simulation_provider import SimulationProvider


def request_payload(scenario: SimulationScenario) -> dict[str, object]:
    return {
        "simulation_scenario": scenario.value,
        "case": {"id": "case-1", "title": "Provider test"},
        "api_token": "must-not-leak",
    }


async def test_adapter_contract_success_health_query_cancel_and_masking() -> None:
    adapter = SimulationProvider()
    assert adapter.validate_configuration(
        {"provider_type": "SIMULATION", "production_enabled": False}
    ) == []
    assert (
        adapter.validate_request("SIMULATE_CASE", request_payload(SimulationScenario.SUCCESS))
        == []
    )
    correlation_id = uuid4()
    prepared = adapter.prepare(
        correlation_id, "SIMULATE_CASE", request_payload(SimulationScenario.SUCCESS)
    )
    assert prepared.payload["api_token"] == "***MASKED***"
    result = await adapter.execute(prepared)
    assert result.normalized_status == "SUCCEEDED"
    assert result.payload["external_effect"] is False
    assert (await adapter.query_status(correlation_id)).normalized_status == "SUCCEEDED"
    assert (await adapter.cancel(correlation_id)).normalized_status == "AMBIGUOUS"
    assert (await adapter.healthcheck()) == {"status": "ready", "external_effect": False}
    assert mask_secrets({"nested": {"password": "value"}}) == {
        "nested": {"password": "***MASKED***"}
    }


@pytest.mark.parametrize(
    ("scenario", "classification"),
    [
        (SimulationScenario.TEMPORARY_ERROR, ProviderErrorClassification.TEMPORARY),
        (SimulationScenario.PERMANENT_ERROR, ProviderErrorClassification.PERMANENT),
        (SimulationScenario.TIMEOUT, ProviderErrorClassification.TIMEOUT),
        (SimulationScenario.RATE_LIMIT, ProviderErrorClassification.RATE_LIMIT),
        (SimulationScenario.INVALID_SIGNATURE, ProviderErrorClassification.INVALID_SIGNATURE),
        (SimulationScenario.INVALID_RESPONSE, ProviderErrorClassification.INVALID_RESPONSE),
    ],
)
async def test_adapter_classifies_simulated_errors(
    scenario: SimulationScenario, classification: ProviderErrorClassification
) -> None:
    adapter = SimulationProvider()
    prepared = adapter.prepare(uuid4(), "SIMULATE_CASE", request_payload(scenario))
    with pytest.raises(ProviderExecutionError) as raised:
        await adapter.execute(prepared)
    assert adapter.classify_error(raised.value) == classification


@pytest.mark.parametrize(
    "scenario",
    [
        SimulationScenario.DUPLICATE_RESPONSE,
        SimulationScenario.DELAYED_RESPONSE,
        SimulationScenario.ALREADY_PROCESSED,
    ],
)
async def test_success_variants_are_normalized_once(scenario: SimulationScenario) -> None:
    adapter = SimulationProvider()
    result = await adapter.execute(
        adapter.prepare(uuid4(), "SIMULATE_CASE", request_payload(scenario))
    )
    assert result.normalized_status == "SUCCEEDED"
    assert result.payload["external_effect"] is False


async def test_ambiguous_status_is_never_normalized_as_success() -> None:
    adapter = SimulationProvider()
    result = await adapter.execute(
        adapter.prepare(
            uuid4(), "SIMULATE_CASE", request_payload(SimulationScenario.AMBIGUOUS_STATUS)
        )
    )
    assert result.normalized_status == "AMBIGUOUS"
    assert result.payload["confirmed"] is False


def test_adapter_validation_rejects_invalid_configuration_and_request() -> None:
    adapter = SimulationProvider()
    assert adapter.validate_configuration(
        {"provider_type": "SIMULATION", "production_enabled": True}
    )
    assert adapter.validate_configuration(
        {"provider_type": "EXTERNAL", "production_enabled": False}
    )
    assert adapter.validate_request("", {"simulation_scenario": "UNKNOWN"})
