"""Provider boundary used by the outbox worker and every future integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from mediaos.domain.enums import ProviderErrorClassification


@dataclass(frozen=True, slots=True)
class PreparedProviderRequest:
    correlation_id: UUID
    operation: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderExecutionResult:
    provider_status: str
    normalized_status: str
    payload: dict[str, Any]
    external_reference: str | None = None


class ProviderExecutionError(RuntimeError):
    def __init__(self, message: str, classification: ProviderErrorClassification) -> None:
        super().__init__(message)
        self.classification = classification


class ProviderAdapter(Protocol):
    def validate_configuration(self, configuration: dict[str, Any]) -> list[str]: ...

    def validate_request(self, operation: str, payload: dict[str, Any]) -> list[str]: ...

    def prepare(
        self, correlation_id: UUID, operation: str, payload: dict[str, Any]
    ) -> PreparedProviderRequest: ...

    async def execute(self, request: PreparedProviderRequest) -> ProviderExecutionResult: ...

    async def query_status(self, correlation_id: UUID) -> ProviderExecutionResult: ...

    async def cancel(self, correlation_id: UUID) -> ProviderExecutionResult: ...

    def normalize_response(self, response: dict[str, Any]) -> ProviderExecutionResult: ...

    def classify_error(self, error: Exception) -> ProviderErrorClassification: ...

    async def healthcheck(self) -> dict[str, Any]: ...


def mask_secrets(value: Any) -> Any:
    """Recursively mask secret-like fields before persistence or API output."""

    if isinstance(value, dict):
        masked: dict[str, Any] = {}
        for key, item in value.items():
            normalized = key.lower().replace("-", "_")
            if any(marker in normalized for marker in ("secret", "password", "token", "api_key")):
                masked[key] = "***MASKED***"
            else:
                masked[key] = mask_secrets(item)
        return masked
    if isinstance(value, list):
        return [mask_secrets(item) for item in value]
    return value
