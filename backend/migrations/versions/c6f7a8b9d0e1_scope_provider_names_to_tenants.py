"""scope provider configuration names to tenants

Revision ID: c6f7a8b9d0e1
Revises: b5e6f7a8c9d0
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c6f7a8b9d0e1"
down_revision: str | None = "b5e6f7a8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_provider_configurations_name",
        "provider_configurations",
        type_="unique",
    )
    op.create_index(
        "uq_provider_configurations_global_name",
        "provider_configurations",
        ["name"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NULL"),
    )
    op.create_index(
        "uq_provider_configurations_tenant_name",
        "provider_configurations",
        ["tenant_id", "name"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_provider_configurations_tenant_name",
        table_name="provider_configurations",
    )
    op.drop_index(
        "uq_provider_configurations_global_name",
        table_name="provider_configurations",
    )
    op.create_unique_constraint(
        "uq_provider_configurations_name",
        "provider_configurations",
        ["name"],
    )
