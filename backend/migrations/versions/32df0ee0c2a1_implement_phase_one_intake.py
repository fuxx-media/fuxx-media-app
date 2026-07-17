"""implement phase one authentication and intake

Revision ID: 32df0ee0c2a1
Revises: 086e30120b92
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "32df0ee0c2a1"
down_revision: str | None = "086e30120b92"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    role_name = postgresql.ENUM(
        "ADMIN",
        "BACKOFFICE",
        "REVIEWER",
        "SYSTEM_WORKER",
        name="role_name",
        create_type=False,
    )
    op.execute("CREATE TYPE role_name AS ENUM ('ADMIN', 'BACKOFFICE', 'REVIEWER', 'SYSTEM_WORKER')")

    op.create_table(
        "tenants",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )
    op.execute(
        sa.text(
            "INSERT INTO tenants (id, name, slug) VALUES "
            "(CAST(:tenant_id AS uuid), 'Legacy Phase 0', 'legacy-phase-zero')"
        ).bindparams(tenant_id=LEGACY_TENANT_ID)
    )
    op.create_table(
        "users",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=500), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", role_name, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "role"),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index(
        "ix_auth_sessions_active", "auth_sessions", ["token_hash", "expires_at", "revoked_at"]
    )

    op.add_column("channels", sa.Column("tenant_id", sa.UUID(), nullable=True))
    op.execute(
        sa.text("UPDATE channels SET tenant_id = CAST(:tenant_id AS uuid)").bindparams(
            tenant_id=LEGACY_TENANT_ID
        )
    )
    op.alter_column("channels", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_channels_tenant_id", "channels", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_index("ix_channels_tenant_id", "channels", ["tenant_id"])
    op.drop_constraint("uq_channels_slug", "channels", type_="unique")
    op.create_unique_constraint("uq_channels_tenant_slug", "channels", ["tenant_id", "slug"])

    op.add_column("content_jobs", sa.Column("tenant_id", sa.UUID(), nullable=True))
    op.execute(
        "UPDATE content_jobs SET tenant_id = channels.tenant_id "
        "FROM channels WHERE content_jobs.channel_id = channels.id"
    )
    op.alter_column("content_jobs", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_content_jobs_tenant_id",
        "content_jobs",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_content_jobs_tenant_id", "content_jobs", ["tenant_id"])
    op.drop_index("ix_content_jobs_state_created", table_name="content_jobs")
    op.create_index(
        "ix_content_jobs_tenant_state_created",
        "content_jobs",
        ["tenant_id", "current_state", "created_at"],
    )

    op.execute("DROP TRIGGER IF EXISTS audit_events_immutable ON audit_events")
    op.add_column("audit_events", sa.Column("tenant_id", sa.UUID(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE audit_events SET tenant_id = "
            "COALESCE(content_jobs.tenant_id, CAST(:tenant_id AS uuid)) "
            "FROM content_jobs WHERE audit_events.job_id = content_jobs.id"
        ).bindparams(tenant_id=LEGACY_TENANT_ID)
    )
    op.execute(
        sa.text(
            "UPDATE audit_events SET tenant_id = CAST(:tenant_id AS uuid) WHERE tenant_id IS NULL"
        ).bindparams(tenant_id=LEGACY_TENANT_ID)
    )
    op.alter_column("audit_events", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_audit_events_tenant_id",
        "audit_events",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"])
    op.execute(
        "CREATE TRIGGER audit_events_immutable BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation()"
    )

    op.create_table(
        "idempotency_records",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("scope", sa.String(length=100), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "scope", "key", name="uq_idempotency_tenant_scope_key"),
    )
    op.create_index("ix_idempotency_created", "idempotency_records", ["created_at"])
    op.create_table(
        "stored_files",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("detected_mime_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("bucket", sa.String(length=100), nullable=False),
        sa.Column("object_key", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint("size_bytes > 0", name="ck_stored_files_size_positive"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bucket", "object_key", name="uq_stored_files_object"),
        sa.UniqueConstraint("tenant_id", "sha256", name="uq_stored_files_tenant_sha256"),
    )
    op.create_index("ix_stored_files_tenant_id", "stored_files", ["tenant_id"])
    op.create_table(
        "job_attachments",
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("stored_file_id", sa.UUID(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["content_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stored_file_id"], ["stored_files.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "stored_file_id", name="uq_job_attachments_job_file"),
    )
    op.create_index("ix_job_attachments_job_id", "job_attachments", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_job_attachments_job_id", table_name="job_attachments")
    op.drop_table("job_attachments")
    op.drop_index("ix_stored_files_tenant_id", table_name="stored_files")
    op.drop_table("stored_files")
    op.drop_index("ix_idempotency_created", table_name="idempotency_records")
    op.drop_table("idempotency_records")
    op.execute("DROP TRIGGER IF EXISTS audit_events_immutable ON audit_events")
    op.drop_index("ix_audit_events_tenant_id", table_name="audit_events")
    op.drop_constraint("fk_audit_events_tenant_id", "audit_events", type_="foreignkey")
    op.drop_column("audit_events", "tenant_id")
    op.execute(
        "CREATE TRIGGER audit_events_immutable BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation()"
    )
    op.drop_index("ix_content_jobs_tenant_state_created", table_name="content_jobs")
    op.create_index(
        "ix_content_jobs_state_created", "content_jobs", ["current_state", "created_at"]
    )
    op.drop_index("ix_content_jobs_tenant_id", table_name="content_jobs")
    op.drop_constraint("fk_content_jobs_tenant_id", "content_jobs", type_="foreignkey")
    op.drop_column("content_jobs", "tenant_id")
    op.drop_constraint("uq_channels_tenant_slug", "channels", type_="unique")
    op.create_unique_constraint("uq_channels_slug", "channels", ["slug"])
    op.drop_index("ix_channels_tenant_id", table_name="channels")
    op.drop_constraint("fk_channels_tenant_id", "channels", type_="foreignkey")
    op.drop_column("channels", "tenant_id")
    op.drop_index("ix_auth_sessions_active", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("user_roles")
    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_table("users")
    op.drop_table("tenants")
    postgresql.ENUM(name="role_name").drop(op.get_bind(), checkfirst=True)
