"""implement phase three provider foundation

Revision ID: b5e6f7a8c9d0
Revises: a4f1c2d3e4f5
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b5e6f7a8c9d0"
down_revision: str | None = "a4f1c2d3e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "provider_feature_flags",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("global_integration_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("dry_run_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("production_execution_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("callback_intake_enabled", sa.Boolean(), server_default="false", nullable=False),
        *_timestamps(),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", name="uq_provider_flags_tenant"),
    )
    op.create_table(
        "secret_references",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("environment_variable", sa.String(length=200), nullable=False),
        sa.Column("purpose", sa.String(length=300), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        *_timestamps(),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_secret_reference_tenant_name"),
    )
    op.create_table(
        "signature_profiles",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("secret_reference_id", sa.UUID(), nullable=False),
        sa.Column("algorithm", sa.String(length=50), server_default="HMAC-SHA256", nullable=False),
        sa.Column("timestamp_tolerance_seconds", sa.Integer(), server_default="300", nullable=False),
        *_timestamps(),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["secret_reference_id"], ["secret_references.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_signature_profile_tenant_name"),
    )

    op.add_column("provider_configurations", sa.Column("tenant_id", sa.UUID()))
    op.add_column("provider_configurations", sa.Column("secret_reference_id", sa.UUID()))
    op.add_column("provider_configurations", sa.Column("signature_profile_id", sa.UUID()))
    op.add_column(
        "provider_configurations",
        sa.Column("dry_run_enabled", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column(
        "provider_configurations",
        sa.Column("production_enabled", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "provider_configurations",
        sa.Column("callback_enabled", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_foreign_key(
        "fk_provider_config_tenant",
        "provider_configurations",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_provider_config_secret",
        "provider_configurations",
        "secret_references",
        ["secret_reference_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_provider_config_signature",
        "provider_configurations",
        "signature_profiles",
        ["signature_profile_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_provider_configurations_tenant_id", "provider_configurations", ["tenant_id"])

    op.create_table(
        "provider_capabilities",
        sa.Column("provider_configuration_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("required_fields", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        *_timestamps(),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["provider_configuration_id"], ["provider_configurations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_configuration_id", "operation", name="uq_provider_capability_operation"),
    )
    op.create_index(
        "ix_provider_capabilities_provider_configuration_id",
        "provider_capabilities",
        ["provider_configuration_id"],
    )
    op.create_table(
        "technical_approvals",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("job_revision", sa.Integer(), nullable=False),
        sa.Column("provider_configuration_id", sa.UUID(), nullable=False),
        sa.Column("capability_id", sa.UUID(), nullable=False),
        sa.Column("approved_by", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="APPROVED", nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["content_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["provider_configuration_id"], ["provider_configurations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["capability_id"], ["provider_capabilities.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_technical_approval_job_revision",
        "technical_approvals",
        ["job_id", "job_revision", "status"],
    )
    op.create_table(
        "execution_orders",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("job_revision", sa.Integer(), nullable=False),
        sa.Column("provider_configuration_id", sa.UUID(), nullable=False),
        sa.Column("capability_id", sa.UUID(), nullable=False),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("business_approval_id", sa.UUID(), nullable=False),
        sa.Column("technical_approval_id", sa.UUID()),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("prepared_payload", sa.JSON(), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("external_effect", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("status", sa.String(length=40), server_default="VALIDATED", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("invalidated_at", sa.DateTime(timezone=True)),
        sa.Column("discard_reason", sa.Text()),
        *_timestamps(),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint("max_attempts > 0", name="ck_execution_max_attempts"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["content_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["provider_configuration_id"], ["provider_configurations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["capability_id"], ["provider_capabilities.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["business_approval_id"], ["approval_requests.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["technical_approval_id"], ["technical_approvals.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_execution_tenant_key"),
        sa.UniqueConstraint(
            "tenant_id",
            "provider_configuration_id",
            "operation",
            "job_id",
            "job_revision",
            "request_fingerprint",
            "dry_run",
            name="uq_execution_effect",
        ),
        sa.UniqueConstraint("correlation_id", name="uq_execution_correlation"),
    )
    op.create_index("ix_execution_status_created", "execution_orders", ["status", "created_at"])
    op.create_table(
        "execution_revisions",
        sa.Column("execution_order_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["execution_order_id"], ["execution_orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_order_id", "revision", name="uq_execution_revision"),
    )
    op.create_table(
        "outbox_events",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("execution_order_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="PENDING", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("locked_by", sa.String(length=200)),
        sa.Column("last_error", sa.Text()),
        *_timestamps(),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["execution_order_id"], ["execution_orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_order_id", "sequence", name="uq_outbox_execution_sequence"),
    )
    op.create_index("ix_outbox_claim", "outbox_events", ["status", "available_at", "created_at"])
    op.create_table(
        "execution_attempts",
        sa.Column("execution_order_id", sa.UUID(), nullable=False),
        sa.Column("outbox_event_id", sa.UUID(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("response_payload", sa.JSON()),
        sa.Column("error_message", sa.Text()),
        sa.Column("error_classification", sa.String(length=30)),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["execution_order_id"], ["execution_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["outbox_event_id"], ["outbox_events.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_order_id", "attempt_number", name="uq_execution_attempt_number"),
    )
    op.create_index(
        "ix_execution_attempt_order_started", "execution_attempts", ["execution_order_id", "started_at"]
    )
    op.create_table(
        "provider_responses",
        sa.Column("execution_order_id", sa.UUID(), nullable=False),
        sa.Column("execution_attempt_id", sa.UUID()),
        sa.Column("provider_status", sa.String(length=100), nullable=False),
        sa.Column("normalized_status", sa.String(length=100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["execution_order_id"], ["execution_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["execution_attempt_id"], ["execution_attempts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "retry_plans",
        sa.Column("execution_order_id", sa.UUID(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("backoff_seconds", sa.Integer(), nullable=False),
        sa.Column("classification", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["execution_order_id"], ["execution_orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_order_id", "attempt_number", name="uq_retry_plan_attempt"),
    )
    op.create_table(
        "dry_run_results",
        sa.Column("execution_order_id", sa.UUID(), nullable=False),
        sa.Column("valid", sa.Boolean(), nullable=False),
        sa.Column("masked_payload", sa.JSON(), nullable=False),
        sa.Column("validation_errors", sa.JSON(), nullable=False),
        sa.Column("external_effect", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["execution_order_id"], ["execution_orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_order_id", name="uq_dry_run_execution"),
    )
    op.create_table(
        "simulation_scenarios",
        sa.Column("provider_configuration_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("scenario", sa.String(length=40), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        *_timestamps(),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["provider_configuration_id"], ["provider_configurations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_configuration_id", "name", name="uq_simulation_scenario_name"),
    )
    op.create_table(
        "callback_receipts",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("provider_configuration_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.String(length=200), nullable=False),
        sa.Column("correlation_id", sa.UUID(), nullable=False),
        sa.Column("provider_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("normalized_response", sa.JSON(), nullable=False),
        sa.Column("signature_valid", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["provider_configuration_id"], ["provider_configurations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_configuration_id", "event_id", name="uq_callback_provider_event"),
    )
    op.create_index("ix_callback_correlation", "callback_receipts", ["correlation_id", "created_at"])
    op.create_table(
        "result_artifacts",
        sa.Column("execution_order_id", sa.UUID(), nullable=False),
        sa.Column("execution_attempt_id", sa.UUID()),
        sa.Column("kind", sa.String(length=100), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("stored_file_id", sa.UUID()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["execution_order_id"], ["execution_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["execution_attempt_id"], ["execution_attempts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["stored_file_id"], ["stored_files.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "CREATE TRIGGER execution_revisions_immutable BEFORE UPDATE OR DELETE ON execution_revisions "
        "FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation()"
    )
    op.execute(
        "CREATE TRIGGER dry_run_results_immutable BEFORE UPDATE OR DELETE ON dry_run_results "
        "FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS dry_run_results_immutable ON dry_run_results")
    op.execute("DROP TRIGGER IF EXISTS execution_revisions_immutable ON execution_revisions")
    op.drop_table("result_artifacts")
    op.drop_index("ix_callback_correlation", table_name="callback_receipts")
    op.drop_table("callback_receipts")
    op.drop_table("simulation_scenarios")
    op.drop_table("dry_run_results")
    op.drop_table("retry_plans")
    op.drop_table("provider_responses")
    op.drop_index("ix_execution_attempt_order_started", table_name="execution_attempts")
    op.drop_table("execution_attempts")
    op.drop_index("ix_outbox_claim", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_table("execution_revisions")
    op.drop_index("ix_execution_status_created", table_name="execution_orders")
    op.drop_table("execution_orders")
    op.drop_index("ix_technical_approval_job_revision", table_name="technical_approvals")
    op.drop_table("technical_approvals")
    op.drop_index("ix_provider_capabilities_provider_configuration_id", table_name="provider_capabilities")
    op.drop_table("provider_capabilities")
    op.drop_index("ix_provider_configurations_tenant_id", table_name="provider_configurations")
    op.drop_constraint("fk_provider_config_signature", "provider_configurations", type_="foreignkey")
    op.drop_constraint("fk_provider_config_secret", "provider_configurations", type_="foreignkey")
    op.drop_constraint("fk_provider_config_tenant", "provider_configurations", type_="foreignkey")
    for column in (
        "callback_enabled",
        "production_enabled",
        "dry_run_enabled",
        "signature_profile_id",
        "secret_reference_id",
        "tenant_id",
    ):
        op.drop_column("provider_configurations", column)
    op.drop_table("signature_profiles")
    op.drop_table("secret_references")
    op.drop_table("provider_feature_flags")
