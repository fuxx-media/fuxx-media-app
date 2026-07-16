"""Shared test configuration with explicit non-production credentials."""

import os
from collections.abc import AsyncIterator, Generator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.config import get_settings
from mediaos.database import close_engine, get_session_factory


@pytest.fixture(autouse=True)
def isolated_settings(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Generator[None, None, None]:
    if request.node.get_closest_marker("integration") is not None:
        if os.getenv("MEDIAOS_RUN_INTEGRATION") != "1":
            pytest.skip("PostgreSQL integration tests require MEDIAOS_RUN_INTEGRATION=1")
        yield
        return
    monkeypatch.setenv("POSTGRES_USER", "test-user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-password-not-a-secret")
    monkeypatch.setenv("POSTGRES_DB", "test-database")
    monkeypatch.setenv("MINIO_ROOT_USER", "test-user")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "test-password-not-a-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def integration_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session
        await session.rollback()


@pytest.fixture(autouse=True)
async def integration_engine_isolation(
    request: pytest.FixtureRequest,
) -> AsyncIterator[None]:
    if request.node.get_closest_marker("integration") is None:
        yield
        return
    await close_engine()
    yield
    async with get_session_factory()() as cleanup_session, cleanup_session.begin():
        await cleanup_session.execute(
            text("TRUNCATE TABLE audit_events, channels, provider_configurations CASCADE")
        )
    await close_engine()
