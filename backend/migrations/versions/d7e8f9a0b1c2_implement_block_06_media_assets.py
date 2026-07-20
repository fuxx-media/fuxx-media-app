"""implement block 06 media assets

Revision ID: d7e8f9a0b1c2
Revises: c6f7a8b9d0e1
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7e8f9a0b1c2"
down_revision: str | None = "c6f7a8b9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    )


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False)


def upgrade() -> None:
    op.execute("ALTER TYPE role_name ADD VALUE IF NOT EXISTS 'READER'")
    op.create_table(
        "media_categories",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("parent_id", sa.UUID()),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("slug", sa.String(150), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        *_timestamps(),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["media_categories.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_media_category_tenant_slug"),
    )
    op.create_index("ix_media_categories_tenant_id", "media_categories", ["tenant_id"])
    op.create_table(
        "media_tags",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("synonyms", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        *_timestamps(),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_media_tag_tenant_name"),
    )
    op.create_index("ix_media_tags_tenant_id", "media_tags", ["tenant_id"])
    op.create_table(
        "media_assets",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column(
            "media_type",
            _enum(
                "media_type",
                "IMAGE",
                "VIDEO",
                "AUDIO",
                "DOCUMENT",
                "GRAPHIC",
                "SUBTITLE",
                "PREVIEW",
                "OTHER",
            ),
            nullable=False,
        ),
        sa.Column("category_id", sa.UUID()),
        sa.Column(
            "status",
            _enum(
                "media_status",
                "DRAFT",
                "UPLOADING",
                "QUARANTINED",
                "TECHNICAL_REVIEW",
                "CONTENT_REVIEW",
                "RIGHTS_REVIEW",
                "CHANGES_REQUESTED",
                "APPROVED",
                "READY",
                "ARCHIVED",
                "REJECTED",
                "DELETION_PENDING",
                "DELETED",
            ),
            server_default="DRAFT",
            nullable=False,
        ),
        sa.Column(
            "technical_status",
            _enum("media_technical_status", "PENDING", "VERIFIED", "QUARANTINED", "FAILED"),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column(
            "approval_status",
            _enum(
                "media_approval_status",
                "NOT_REQUESTED",
                "PENDING",
                "APPROVED",
                "REJECTED",
                "INVALIDATED",
            ),
            server_default="NOT_REQUESTED",
            nullable=False,
        ),
        sa.Column(
            "storage_status",
            _enum("media_storage_status", "PENDING", "STORED", "VERIFIED", "DELETED"),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("current_version_number", sa.Integer(), server_default="0", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("assigned_to", sa.UUID()),
        sa.Column(
            "retention_status",
            _enum(
                "retention_status",
                "ACTIVE",
                "ARCHIVED",
                "RETENTION_HOLD",
                "DELETION_REQUESTED",
                "DELETION_APPROVED",
                "DELETED_LOGICALLY",
                "PURGED",
            ),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column(
            "confidentiality",
            _enum("confidentiality_class", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"),
            server_default="INTERNAL",
            nullable=False,
        ),
        sa.Column("deletion_locked", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("archived", sa.Boolean(), server_default="false", nullable=False),
        *_timestamps(),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint("current_version_number >= 0", name="ck_media_asset_version_nonnegative"),
        sa.CheckConstraint("revision >= 1", name="ck_media_asset_revision_positive"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["category_id"], ["media_categories.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_media_assets_tenant_id", "media_assets", ["tenant_id"])
    op.create_index(
        "ix_media_asset_tenant_status_updated",
        "media_assets",
        ["tenant_id", "status", "updated_at"],
    )
    op.add_column("audit_events", sa.Column("media_asset_id", sa.UUID()))
    op.create_foreign_key(
        "fk_audit_event_media_asset",
        "audit_events",
        "media_assets",
        ["media_asset_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_audit_events_media_asset_id", "audit_events", ["media_asset_id"])
    op.create_table(
        "media_files",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("bucket", sa.String(100), nullable=False),
        sa.Column("object_key", sa.String(500), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("detected_mime_type", sa.String(100), nullable=False),
        sa.Column("file_signature", sa.String(100), nullable=False),
        sa.Column("upload_status", sa.String(30), server_default="COMPLETED", nullable=False),
        sa.Column(
            "verification_status",
            _enum("media_verification_status", "PENDING", "VERIFIED", "REJECTED"),
            server_default="VERIFIED",
            nullable=False,
        ),
        sa.Column(
            "storage_status",
            _enum("media_storage_status", "PENDING", "STORED", "VERIFIED", "DELETED"),
            server_default="STORED",
            nullable=False,
        ),
        sa.Column(
            "stored_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("last_integrity_check_at", sa.DateTime(timezone=True)),
        sa.Column("quarantined", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint("size_bytes > 0", name="ck_media_file_size_positive"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "sha256", "size_bytes", name="uq_media_file_binary"),
        sa.UniqueConstraint("bucket", "object_key", name="uq_media_file_object"),
    )
    op.create_index("ix_media_files_tenant_id", "media_files", ["tenant_id"])
    op.create_table(
        "media_versions",
        sa.Column("media_asset_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("media_file_id", sa.UUID(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("claimed_mime_type", sa.String(100)),
        sa.Column("detected_mime_type", sa.String(100), nullable=False),
        sa.Column(
            "detected_media_type",
            _enum(
                "media_type",
                "IMAGE",
                "VIDEO",
                "AUDIO",
                "DOCUMENT",
                "GRAPHIC",
                "SUBTITLE",
                "PREVIEW",
                "OTHER",
            ),
            nullable=False,
        ),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column("technical_results", sa.JSON(), nullable=False),
        sa.Column(
            "approval_status",
            _enum(
                "media_approval_status",
                "NOT_REQUESTED",
                "PENDING",
                "APPROVED",
                "REJECTED",
                "INVALIDATED",
            ),
            server_default="NOT_REQUESTED",
            nullable=False,
        ),
        sa.Column("is_current", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("superseded_by_id", sa.UUID()),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["media_file_id"], ["media_files.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["superseded_by_id"], ["media_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("media_asset_id", "version_number", name="uq_media_version_number"),
    )
    op.create_index(
        "ix_media_version_asset_current", "media_versions", ["media_asset_id", "is_current"]
    )
    op.create_table(
        "media_metadata",
        sa.Column("media_version_id", sa.UUID(), nullable=False),
        sa.Column("technical", sa.JSON(), nullable=False),
        sa.Column("business", sa.JSON(), nullable=False),
        sa.Column("custom", sa.JSON(), nullable=False),
        sa.Column("system_generated", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["media_version_id"], ["media_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("media_version_id", name="uq_media_metadata_version"),
    )
    op.create_table(
        "media_asset_tags",
        sa.Column("media_asset_id", sa.UUID(), nullable=False),
        sa.Column("tag_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["media_tags.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("media_asset_id", "tag_id"),
    )
    op.create_table(
        "media_variants",
        sa.Column("source_version_id", sa.UUID(), nullable=False),
        sa.Column("variant_type", sa.String(80), nullable=False),
        sa.Column("technical_properties", sa.JSON(), nullable=False),
        sa.Column("media_file_id", sa.UUID()),
        sa.Column(
            "generation_status",
            _enum("media_variant_status", "REGISTERED", "READY", "FAILED"),
            nullable=False,
        ),
        sa.Column("generation_source", sa.String(100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("verification_result", sa.JSON(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["source_version_id"], ["media_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_file_id"], ["media_files.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_version_id", "variant_type", name="uq_media_variant_type"),
    )
    op.create_table(
        "media_relations",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("source_asset_id", sa.UUID(), nullable=False),
        sa.Column("target_asset_id", sa.UUID(), nullable=False),
        sa.Column(
            "relation_type",
            _enum(
                "media_relation_type",
                "BELONGS_TO",
                "REPLACES",
                "DERIVED_FROM",
                "PREVIEW_OF",
                "PART_OF",
                "LANGUAGE_VARIANT_OF",
                "LINKED_WITH",
                "DUPLICATE_OF",
            ),
            nullable=False,
        ),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint("source_asset_id <> target_asset_id", name="ck_media_relation_not_self"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_asset_id"], ["media_assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["target_asset_id"], ["media_assets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_asset_id", "target_asset_id", "relation_type", name="uq_media_relation"
        ),
    )
    op.create_index("ix_media_relations_tenant_id", "media_relations", ["tenant_id"])
    op.create_table(
        "media_rights",
        sa.Column("media_asset_id", sa.UUID(), nullable=False),
        sa.Column("rights_holder", sa.String(300), nullable=False),
        sa.Column("license_type", sa.String(150), nullable=False),
        sa.Column("usage_start", sa.DateTime(timezone=True)),
        sa.Column("usage_end", sa.DateTime(timezone=True)),
        sa.Column("allowed_uses", sa.JSON(), nullable=False),
        sa.Column("allowed_regions", sa.JSON(), nullable=False),
        sa.Column("allowed_channels", sa.JSON(), nullable=False),
        sa.Column("attribution_required", sa.Boolean(), nullable=False),
        sa.Column("editing_allowed", sa.Boolean(), nullable=False),
        sa.Column("redistribution_allowed", sa.Boolean(), nullable=False),
        sa.Column("restrictions", sa.Text()),
        sa.Column("proof_media_asset_id", sa.UUID()),
        sa.Column(
            "review_status",
            _enum(
                "rights_review_status", "PENDING", "APPROVED", "REJECTED", "EXPIRED", "CONFLICT"
            ),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("reviewed_by", sa.UUID()),
        sa.Column("review_reason", sa.Text()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["proof_media_asset_id"], ["media_assets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("media_asset_id", name="uq_media_rights_asset"),
    )
    op.create_table(
        "media_approvals",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("media_asset_id", sa.UUID(), nullable=False),
        sa.Column("media_version_id", sa.UUID(), nullable=False),
        sa.Column("requested_by", sa.UUID(), nullable=False),
        sa.Column("resolved_by", sa.UUID()),
        sa.Column(
            "status",
            _enum(
                "media_approval_status",
                "NOT_REQUESTED",
                "PENDING",
                "APPROVED",
                "REJECTED",
                "INVALIDATED",
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_version_id"], ["media_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_media_approval_version_status", "media_approvals", ["media_version_id", "status"]
    )
    op.create_table(
        "media_collections",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column(
            "visibility",
            _enum("media_collection_visibility", "PRIVATE", "TENANT"),
            nullable=False,
        ),
        sa.Column(
            "status", _enum("media_collection_status", "ACTIVE", "ARCHIVED"), nullable=False
        ),
        *_timestamps(),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_media_collection_name"),
    )
    op.create_index("ix_media_collections_tenant_id", "media_collections", ["tenant_id"])
    op.create_table(
        "media_collection_items",
        sa.Column("collection_id", sa.UUID(), nullable=False),
        sa.Column("media_asset_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("added_by", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["collection_id"], ["media_collections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_assets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("collection_id", "media_asset_id", name="uq_media_collection_item"),
        sa.UniqueConstraint("collection_id", "position", name="uq_media_collection_position"),
    )
    op.create_table(
        "media_collection_history",
        sa.Column("collection_id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=False),
        sa.Column("change_type", sa.String(100), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["collection_id"], ["media_collections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "media_deletion_requests",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("media_asset_id", sa.UUID(), nullable=False),
        sa.Column("requested_by", sa.UUID(), nullable=False),
        sa.Column("approved_by", sa.UUID()),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), server_default="REQUESTED", nullable=False),
        sa.Column(
            "requested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_assets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "media_tasks",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("media_asset_id", sa.UUID(), nullable=False),
        sa.Column("media_version_id", sa.UUID()),
        sa.Column("task_type", sa.String(100), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING", "RUNNING", "SUCCEEDED", "RETRY", "FAILED", name="task_status", create_type=False
            ),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("locked_by", sa.String(200)),
        sa.Column("last_error", sa.Text()),
        *_timestamps(),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_version_id"], ["media_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("media_version_id", "task_type", name="uq_media_task_version_type"),
    )
    op.create_index(
        "ix_media_task_claim", "media_tasks", ["status", "available_at", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_media_task_claim", table_name="media_tasks")
    op.drop_table("media_tasks")
    op.drop_table("media_deletion_requests")
    op.drop_table("media_collection_history")
    op.drop_table("media_collection_items")
    op.drop_index("ix_media_collections_tenant_id", table_name="media_collections")
    op.drop_table("media_collections")
    op.drop_index("ix_media_approval_version_status", table_name="media_approvals")
    op.drop_table("media_approvals")
    op.drop_table("media_rights")
    op.drop_index("ix_media_relations_tenant_id", table_name="media_relations")
    op.drop_table("media_relations")
    op.drop_table("media_variants")
    op.drop_table("media_asset_tags")
    op.drop_table("media_metadata")
    op.drop_index("ix_media_version_asset_current", table_name="media_versions")
    op.drop_table("media_versions")
    op.drop_index("ix_media_files_tenant_id", table_name="media_files")
    op.drop_table("media_files")
    op.drop_index("ix_audit_events_media_asset_id", table_name="audit_events")
    op.drop_constraint("fk_audit_event_media_asset", "audit_events", type_="foreignkey")
    op.drop_column("audit_events", "media_asset_id")
    op.drop_index("ix_media_asset_tenant_status_updated", table_name="media_assets")
    op.drop_index("ix_media_assets_tenant_id", table_name="media_assets")
    op.drop_table("media_assets")
    op.drop_index("ix_media_tags_tenant_id", table_name="media_tags")
    op.drop_table("media_tags")
    op.drop_index("ix_media_categories_tenant_id", table_name="media_categories")
    op.drop_table("media_categories")
    # PostgreSQL enum values cannot be safely removed without rebuilding the type.
