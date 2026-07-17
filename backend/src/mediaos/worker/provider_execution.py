"""Outbox worker entry point for provider executions."""

import logging

from mediaos.application.provider_contract import PreparedProviderRequest
from mediaos.database import get_session_factory
from mediaos.infrastructure.provider_execution_repository import (
    ProviderExecutionRepository,
)
from mediaos.infrastructure.simulation_provider import get_provider_adapter

LOGGER = logging.getLogger(__name__)


async def process_one_provider_execution(*, worker_id: str = "mediaos-provider-worker") -> bool:
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            repository = ProviderExecutionRepository(session)
            recovered = await repository.recover_stale()
            if recovered:
                LOGGER.warning("recovered %s stale provider execution claims", recovered)
            claimed = await repository.claim_next(worker_id=worker_id)
        if claimed is None:
            return False
        adapter = get_provider_adapter(claimed.provider_type)
        request = PreparedProviderRequest(
            correlation_id=claimed.correlation_id,
            operation=claimed.operation,
            payload=claimed.prepared_payload,
        )
        try:
            result = await adapter.execute(request)
        except Exception as exc:
            classification = adapter.classify_error(exc)
            async with session.begin():
                await ProviderExecutionRepository(session).fail(
                    claimed, message=str(exc), classification=classification
                )
            LOGGER.warning(
                "provider execution %s failed with %s", claimed.order_id, classification.value
            )
            return True
        async with session.begin():
            await ProviderExecutionRepository(session).succeed(claimed, result)
        LOGGER.info("provider execution %s processed", claimed.order_id)
        return True
