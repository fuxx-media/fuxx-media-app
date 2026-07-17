"""implement phase two case processing

Revision ID: a4f1c2d3e4f5
Revises: 32df0ee0c2a1
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4f1c2d3e4f5"
down_revision: str | None = "32df0ee0c2a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("content_jobs", sa.Column("category", sa.String(length=100)))
    op.add_column(
        "content_jobs",
        sa.Column("priority", sa.String(length=20), server_default="NORMAL", nullable=False),
    )
    op.add_column(
        "content_jobs",
        sa.Column("business_status", sa.String(length=30), server_default="OPEN", nullable=False),
    )
    op.add_column("content_jobs", sa.Column("assigned_to", sa.UUID()))
    op.add_column("content_jobs", sa.Column("claimed_by", sa.UUID()))
    op.add_column("content_jobs", sa.Column("claim_started_at", sa.DateTime(timezone=True)))
    op.add_column("content_jobs", sa.Column("claim_expires_at", sa.DateTime(timezone=True)))
    op.add_column("content_jobs", sa.Column("claim_version", sa.Integer()))
    op.add_column("content_jobs", sa.Column("due_at", sa.DateTime(timezone=True)))
    op.add_column("content_jobs", sa.Column("last_material_actor_id", sa.UUID()))
    op.add_column("content_jobs", sa.Column("completed_reason", sa.Text()))
    op.create_foreign_key(
        "fk_content_jobs_assigned_to",
        "content_jobs",
        "users",
        ["assigned_to"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_content_jobs_claimed_by",
        "content_jobs",
        "users",
        ["claimed_by"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_content_jobs_assigned_to", "content_jobs", ["assigned_to"])
    op.create_index("ix_content_jobs_claimed_by", "content_jobs", ["claimed_by"])
    op.create_index("ix_content_jobs_claim_expires_at", "content_jobs", ["claim_expires_at"])
    op.create_index("ix_content_jobs_due_at", "content_jobs", ["due_at"])
    op.create_index(
        "ix_content_jobs_tenant_business_priority",
        "content_jobs",
        ["tenant_id", "business_status", "priority", "created_at"],
    )

    op.add_column("approval_requests", sa.Column("job_revision", sa.Integer()))
    op.execute(
        "UPDATE approval_requests SET job_revision = content_jobs.version "
        "FROM content_jobs WHERE approval_requests.job_id = content_jobs.id"
    )
    op.alter_column(
        "approval_requests", "job_revision", nullable=False, server_default="1"
    )
    op.add_column("approval_requests", sa.Column("claimed_by", sa.UUID()))
    op.add_column("approval_requests", sa.Column("claimed_at", sa.DateTime(timezone=True)))
    op.add_column("approval_requests", sa.Column("invalidated_at", sa.DateTime(timezone=True)))
    op.create_index(
        "ix_approval_requests_revision",
        "approval_requests",
        ["job_id", "job_revision", "invalidated_at"],
    )

    op.create_table(
        "case_revisions",
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=False),
        sa.Column("change_type", sa.String(length=100), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["content_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "revision", name="uq_case_revision"),
    )
    op.create_index("ix_case_revisions_job_id", "case_revisions", ["job_id"])
    op.create_table(
        "internal_notes",
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("job_revision", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.UUID(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["content_jobs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_internal_notes_job_created", "internal_notes", ["job_id", "created_at"])
    op.create_table(
        "checklist_items",
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("required", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("completed_by", sa.UUID()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["content_jobs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "position", name="uq_checklist_job_position"),
    )
    op.create_index("ix_checklist_job_required", "checklist_items", ["job_id", "required"])
    op.create_table(
        "case_evidence",
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("job_revision", sa.Integer(), nullable=False),
        sa.Column("stored_file_id", sa.UUID()),
        sa.Column("source", sa.String(length=300), nullable=False),
        sa.Column("structured_data", sa.JSON(), nullable=False),
        sa.Column(
            "verification_status", sa.String(length=30), server_default="UNVERIFIED", nullable=False
        ),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["content_jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["stored_file_id"], ["stored_files.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_case_evidence_job_created", "case_evidence", ["job_id", "created_at"])
    op.execute(
        "CREATE TRIGGER internal_notes_immutable BEFORE UPDATE OR DELETE ON internal_notes "
        "FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation()"
    )
    op.execute(
        "CREATE TRIGGER case_revisions_immutable BEFORE UPDATE OR DELETE ON case_revisions "
        "FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS case_revisions_immutable ON case_revisions")
    op.execute("DROP TRIGGER IF EXISTS internal_notes_immutable ON internal_notes")
    op.drop_index("ix_case_evidence_job_created", table_name="case_evidence")
    op.drop_table("case_evidence")
    op.drop_index("ix_checklist_job_required", table_name="checklist_items")
    op.drop_table("checklist_items")
    op.drop_index("ix_internal_notes_job_created", table_name="internal_notes")
    op.drop_table("internal_notes")
    op.drop_index("ix_case_revisions_job_id", table_name="case_revisions")
    op.drop_table("case_revisions")
    op.drop_index("ix_approval_requests_revision", table_name="approval_requests")
    op.drop_column("approval_requests", "invalidated_at")
    op.drop_column("approval_requests", "claimed_at")
    op.drop_column("approval_requests", "claimed_by")
    op.drop_column("approval_requests", "job_revision")
    op.drop_index("ix_content_jobs_tenant_business_priority", table_name="content_jobs")
    op.drop_index("ix_content_jobs_due_at", table_name="content_jobs")
    op.drop_index("ix_content_jobs_claim_expires_at", table_name="content_jobs")
    op.drop_index("ix_content_jobs_claimed_by", table_name="content_jobs")
    op.drop_index("ix_content_jobs_assigned_to", table_name="content_jobs")
    op.drop_constraint("fk_content_jobs_claimed_by", "content_jobs", type_="foreignkey")
    op.drop_constraint("fk_content_jobs_assigned_to", "content_jobs", type_="foreignkey")
    for column in (
        "completed_reason",
        "last_material_actor_id",
        "due_at",
        "claim_version",
        "claim_expires_at",
        "claim_started_at",
        "claimed_by",
        "assigned_to",
        "business_status",
        "priority",
        "category",
    ):
        op.drop_column("content_jobs", column)
