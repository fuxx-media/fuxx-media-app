from collections.abc import Awaitable, Callable

import pytest
from fastapi.testclient import TestClient

from mediaos.api import health as health_module
from mediaos.main import app


def dependency_state(value: bool) -> Callable[[], Awaitable[bool]]:
    async def check() -> bool:
        return value

    return check


def test_health_and_version_are_read_only_metadata() -> None:
    with TestClient(app) as client:
        health_response = client.get("/api/v1/health")
        version_response = client.get("/api/v1/version")

    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}
    assert version_response.status_code == 200
    assert version_response.json() == {
        "name": "MediaOS",
        "version": "0.1.0",
        "phase": "Phase 0",
    }


def test_ready_is_positive_when_dependencies_are_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(health_module, "database_ready", dependency_state(True))
    monkeypatch.setattr(health_module, "object_storage_ready", dependency_state(True))

    with TestClient(app) as client:
        response = client.get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "dependencies": {"postgres": True, "minio": True},
    }


def test_ready_is_negative_when_a_dependency_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(health_module, "database_ready", dependency_state(False))
    monkeypatch.setattr(health_module, "object_storage_ready", dependency_state(True))

    with TestClient(app) as client:
        response = client.get("/api/v1/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "dependencies": {"postgres": False, "minio": True},
    }
