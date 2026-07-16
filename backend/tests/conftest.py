"""Shared test configuration with explicit non-production credentials."""

from collections.abc import Generator

import pytest

from mediaos.config import get_settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("POSTGRES_USER", "test-user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-password-not-a-secret")
    monkeypatch.setenv("POSTGRES_DB", "test-database")
    monkeypatch.setenv("MINIO_ROOT_USER", "test-user")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "test-password-not-a-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
