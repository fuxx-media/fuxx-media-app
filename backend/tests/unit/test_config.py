import pytest

from mediaos.config import get_frontend_origins, get_settings


def test_database_url_repr_hides_password() -> None:
    settings = get_settings()

    assert "test-password-not-a-secret" not in repr(settings.async_database_url)
    assert settings.async_database_url.drivername == "postgresql+asyncpg"


def test_minio_health_url_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINIO_ENDPOINT", "http://minio:9000/")
    get_settings.cache_clear()

    assert get_settings().minio_health_url == "http://minio:9000/minio/health/ready"


def test_frontend_origins_are_explicit_and_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "MEDIAOS_FRONTEND_ORIGINS",
        "http://localhost:3000, http://127.0.0.1:3000",
    )

    assert get_frontend_origins() == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
