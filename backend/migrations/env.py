"""Alembic migration environment."""

from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import VARCHAR, Enum, create_engine, pool

from mediaos.config import get_settings
from mediaos.domain.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _compare_column_types(
    _migration_context: Any,
    _inspected_column: Any,
    _metadata_column: Any,
    inspected_type: Any,
    metadata_type: Any,
) -> bool | None:
    """Treat non-native SQLAlchemy enums as their VARCHAR storage type.

    The migrations intentionally persist these application enums as VARCHAR columns. Keep
    Alembic's default comparison for every other type, and still flag a VARCHAR that is too
    narrow for the enum metadata.
    """
    if (
        isinstance(metadata_type, Enum)
        and not metadata_type.native_enum
        and isinstance(inspected_type, VARCHAR)
    ):
        required_length = metadata_type.length
        actual_length = inspected_type.length
        if required_length is not None and actual_length is not None:
            return actual_length < required_length
        return False
    return None


def run_migrations_offline() -> None:
    settings = get_settings()
    context.configure(
        url=settings.sync_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=_compare_column_types,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    settings = get_settings()
    connectable = create_engine(
        settings.sync_database_url,
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=_compare_column_types,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
