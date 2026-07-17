"""Environment-only application configuration."""

import os
from functools import lru_cache

from pydantic import AnyHttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables.

    Required credentials deliberately have no defaults so an application process
    cannot start against an accidental or fabricated credential set.
    """

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    mediaos_log_level: str = "INFO"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str
    postgres_password: SecretStr
    postgres_db: str
    minio_endpoint: AnyHttpUrl = AnyHttpUrl("http://localhost:9000")
    minio_root_user: SecretStr
    minio_root_password: SecretStr
    mediaos_private_bucket: str = "mediaos-private"
    mediaos_upload_max_bytes: int = 10 * 1024 * 1024
    mediaos_session_ttl_seconds: int = 8 * 60 * 60
    mediaos_cookie_secure: bool = False

    @property
    def async_database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    @property
    def sync_database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

    @property
    def minio_health_url(self) -> str:
        return f"{str(self.minio_endpoint).rstrip('/')}/minio/health/ready"

    @property
    def minio_connection(self) -> tuple[str, bool]:
        endpoint = str(self.minio_endpoint).rstrip("/")
        secure = endpoint.startswith("https://")
        return endpoint.removeprefix("https://").removeprefix("http://"), secure


def get_frontend_origins() -> list[str]:
    configured = os.getenv(
        "MEDIAOS_FRONTEND_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    )
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
