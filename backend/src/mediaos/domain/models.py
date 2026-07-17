"""SQLAlchemy models for the Phase 0 workflow kernel."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from mediaos.domain.enums import (
    ActorType,
    ApprovalStatus,
    ArtifactKind,
    CallbackStatus,
    CasePriority,
    CaseStatus,
    EvidenceVerificationStatus,
    ExecutionAttemptStatus,
    ExecutionStatus,
    OutboxStatus,
    ProviderCallStatus,
    ProviderErrorClassification,
    RetryPlanStatus,
    RoleName,
    SimulationScenario,
    TaskStatus,
    TechnicalApprovalStatus,
    WorkflowState,
)


class Base(DeclarativeBase):
    pass


class IdentityMixin:
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Tenant(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "tenants"
    __table_args__ = (UniqueConstraint("slug", name="uq_tenants_slug"),)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class User(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),)

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(500), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    roles: Mapped[list[UserRole]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[RoleName] = mapped_column(
        Enum(RoleName, name="role_name"), primary_key=True, nullable=False
    )
    user: Mapped[User] = relationship(back_populates="roles")


class AuthSession(IdentityMixin, Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        Index("ix_auth_sessions_active", "token_hash", "expires_at", "revoked_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Channel(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "channels"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_channels_tenant_slug"),)

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    jobs: Mapped[list[ContentJob]] = relationship(back_populates="channel")


class ContentJob(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "content_jobs"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_content_jobs_version_positive"),
        CheckConstraint("budget_limit_cents >= 0", name="ck_content_jobs_budget_nonnegative"),
        CheckConstraint("spent_cents >= 0", name="ck_content_jobs_spent_nonnegative"),
        Index("ix_content_jobs_tenant_state_created", "tenant_id", "current_state", "created_at"),
        Index(
            "ix_content_jobs_tenant_business_priority",
            "tenant_id",
            "business_status",
            "priority",
            "created_at",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    channel_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    current_state: Mapped[WorkflowState] = mapped_column(
        Enum(WorkflowState, name="workflow_state"),
        nullable=False,
        default=WorkflowState.DRAFT,
        server_default=WorkflowState.DRAFT.value,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    budget_limit_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    spent_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    category: Mapped[str | None] = mapped_column(String(100))
    priority: Mapped[CasePriority] = mapped_column(
        Enum(CasePriority, name="case_priority", native_enum=False),
        nullable=False,
        default=CasePriority.NORMAL,
        server_default=CasePriority.NORMAL.value,
    )
    business_status: Mapped[CaseStatus] = mapped_column(
        Enum(CaseStatus, name="case_status", native_enum=False),
        nullable=False,
        default=CaseStatus.OPEN,
        server_default=CaseStatus.OPEN.value,
    )
    assigned_to: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    claimed_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    claim_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    claim_version: Mapped[int | None] = mapped_column(Integer)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_material_actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    completed_reason: Mapped[str | None] = mapped_column(Text)

    channel: Mapped[Channel] = relationship(back_populates="jobs")
    transitions: Mapped[list[WorkflowTransition]] = relationship(back_populates="job")
    audit_events: Mapped[list[AuditEvent]] = relationship(back_populates="job")


class WorkflowTransition(IdentityMixin, Base):
    __tablename__ = "workflow_transitions"
    __table_args__ = (Index("ix_workflow_transitions_job_created", "job_id", "created_at"),)

    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_jobs.id", ondelete="CASCADE"), nullable=False
    )
    from_state: Mapped[WorkflowState] = mapped_column(
        Enum(WorkflowState, name="workflow_state", create_type=False), nullable=False
    )
    to_state: Mapped[WorkflowState] = mapped_column(
        Enum(WorkflowState, name="workflow_state", create_type=False), nullable=False
    )
    actor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    actor_type: Mapped[ActorType] = mapped_column(
        Enum(ActorType, name="actor_type"), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text)
    job_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    job: Mapped[ContentJob] = relationship(back_populates="transitions")


class AuditEvent(IdentityMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_job_created", "job_id", "created_at"),)

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_jobs.id", ondelete="SET NULL"), index=True
    )
    actor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    actor_type: Mapped[ActorType] = mapped_column(
        Enum(ActorType, name="actor_type", create_type=False)
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    job: Mapped[ContentJob | None] = relationship(back_populates="audit_events")


class ProviderConfiguration(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "provider_configurations"
    __table_args__ = (
        Index(
            "uq_provider_configurations_global_name",
            "name",
            unique=True,
            postgresql_where=text("tenant_id IS NULL"),
        ),
        Index(
            "uq_provider_configurations_tenant_name",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("tenant_id IS NOT NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    tenant_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    provider_type: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    secret_reference_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("secret_references.id", ondelete="RESTRICT")
    )
    signature_profile_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("signature_profiles.id", ondelete="RESTRICT")
    )
    dry_run_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    production_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    callback_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


class ProviderCall(IdentityMixin, Base):
    __tablename__ = "provider_calls"
    __table_args__ = (
        CheckConstraint("cost_cents >= 0", name="ck_provider_calls_cost_nonnegative"),
        Index("ix_provider_calls_job_created", "job_id", "created_at"),
    )

    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_jobs.id", ondelete="CASCADE"), nullable=False
    )
    provider_configuration_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("provider_configurations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[ProviderCallStatus] = mapped_column(
        Enum(ProviderCallStatus, name="provider_call_status"), nullable=False
    )
    request_reference: Mapped[str | None] = mapped_column(String(500))
    response_reference: Mapped[str | None] = mapped_column(String(500))
    cost_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderFeatureFlags(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "provider_feature_flags"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_provider_flags_tenant"),)

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    global_integration_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    dry_run_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    production_execution_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    callback_intake_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )


class SecretReference(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "secret_references"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_secret_reference_tenant_name"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    environment_variable: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose: Mapped[str] = mapped_column(String(300), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class SignatureProfile(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "signature_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_signature_profile_tenant_name"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    secret_reference_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("secret_references.id", ondelete="RESTRICT"),
        nullable=False,
    )
    algorithm: Mapped[str] = mapped_column(
        String(50), nullable=False, default="HMAC-SHA256", server_default="HMAC-SHA256"
    )
    timestamp_tolerance_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=300, server_default="300"
    )


class ProviderCapability(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "provider_capabilities"
    __table_args__ = (
        UniqueConstraint(
            "provider_configuration_id", "operation", name="uq_provider_capability_operation"
        ),
    )

    provider_configuration_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("provider_configurations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    required_fields: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class TechnicalApproval(IdentityMixin, Base):
    __tablename__ = "technical_approvals"
    __table_args__ = (
        Index("ix_technical_approval_job_revision", "job_id", "job_revision", "status"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_jobs.id", ondelete="CASCADE"), nullable=False
    )
    job_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_configuration_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("provider_configurations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    capability_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("provider_capabilities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    approved_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    status: Mapped[TechnicalApprovalStatus] = mapped_column(
        Enum(TechnicalApprovalStatus, name="technical_approval_status", native_enum=False),
        nullable=False,
        default=TechnicalApprovalStatus.APPROVED,
        server_default=TechnicalApprovalStatus.APPROVED.value,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExecutionOrder(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "execution_orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_execution_tenant_key"),
        UniqueConstraint(
            "tenant_id",
            "provider_configuration_id",
            "operation",
            "job_id",
            "job_revision",
            "request_fingerprint",
            "dry_run",
            name="uq_execution_effect",
        ),
        UniqueConstraint("correlation_id", name="uq_execution_correlation"),
        CheckConstraint("max_attempts > 0", name="ck_execution_max_attempts"),
        Index("ix_execution_status_created", "status", "created_at"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_jobs.id", ondelete="CASCADE"), nullable=False
    )
    job_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_configuration_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("provider_configurations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    capability_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("provider_capabilities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    business_approval_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("approval_requests.id", ondelete="RESTRICT"),
        nullable=False,
    )
    technical_approval_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("technical_approvals.id", ondelete="RESTRICT")
    )
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), default=uuid4, nullable=False
    )
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    prepared_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    external_effect: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    status: Mapped[ExecutionStatus] = mapped_column(
        Enum(ExecutionStatus, name="execution_status", native_enum=False),
        nullable=False,
        default=ExecutionStatus.VALIDATED,
        server_default=ExecutionStatus.VALIDATED.value,
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discard_reason: Mapped[str | None] = mapped_column(Text)


class ExecutionRevision(IdentityMixin, Base):
    __tablename__ = "execution_revisions"
    __table_args__ = (
        UniqueConstraint("execution_order_id", "revision", name="uq_execution_revision"),
    )

    execution_order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("execution_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OutboxEvent(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("execution_order_id", "sequence", name="uq_outbox_execution_sequence"),
        Index("ix_outbox_claim", "status", "available_at", "created_at"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    execution_order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("execution_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[OutboxStatus] = mapped_column(
        Enum(OutboxStatus, name="outbox_status", native_enum=False),
        nullable=False,
        default=OutboxStatus.PENDING,
        server_default=OutboxStatus.PENDING.value,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(200))
    last_error: Mapped[str | None] = mapped_column(Text)


class ExecutionAttempt(IdentityMixin, Base):
    __tablename__ = "execution_attempts"
    __table_args__ = (
        UniqueConstraint(
            "execution_order_id", "attempt_number", name="uq_execution_attempt_number"
        ),
        Index("ix_execution_attempt_order_started", "execution_order_id", "started_at"),
    )

    execution_order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("execution_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    outbox_event_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("outbox_events.id", ondelete="RESTRICT"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[ExecutionAttemptStatus] = mapped_column(
        Enum(ExecutionAttemptStatus, name="execution_attempt_status", native_enum=False),
        nullable=False,
        default=ExecutionAttemptStatus.RUNNING,
    )
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    response_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    error_classification: Mapped[ProviderErrorClassification | None] = mapped_column(
        Enum(ProviderErrorClassification, name="provider_error_classification", native_enum=False)
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderResponse(IdentityMixin, Base):
    __tablename__ = "provider_responses"

    execution_order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("execution_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    execution_attempt_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("execution_attempts.id", ondelete="SET NULL")
    )
    provider_status: Mapped[str] = mapped_column(String(100), nullable=False)
    normalized_status: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RetryPlan(IdentityMixin, Base):
    __tablename__ = "retry_plans"
    __table_args__ = (
        UniqueConstraint("execution_order_id", "attempt_number", name="uq_retry_plan_attempt"),
    )

    execution_order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("execution_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    backoff_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    classification: Mapped[ProviderErrorClassification] = mapped_column(
        Enum(ProviderErrorClassification, name="provider_error_classification", native_enum=False),
        nullable=False,
    )
    status: Mapped[RetryPlanStatus] = mapped_column(
        Enum(RetryPlanStatus, name="retry_plan_status", native_enum=False),
        nullable=False,
        default=RetryPlanStatus.SCHEDULED,
    )


class DryRunResult(IdentityMixin, Base):
    __tablename__ = "dry_run_results"
    __table_args__ = (
        UniqueConstraint("execution_order_id", name="uq_dry_run_execution"),
    )

    execution_order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("execution_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    masked_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    validation_errors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    external_effect: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SimulationScenarioConfiguration(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "simulation_scenarios"
    __table_args__ = (
        UniqueConstraint("provider_configuration_id", "name", name="uq_simulation_scenario_name"),
    )

    provider_configuration_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("provider_configurations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    scenario: Mapped[SimulationScenario] = mapped_column(
        Enum(SimulationScenario, name="simulation_scenario", native_enum=False), nullable=False
    )
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class CallbackReceipt(IdentityMixin, Base):
    __tablename__ = "callback_receipts"
    __table_args__ = (
        UniqueConstraint(
            "provider_configuration_id", "event_id", name="uq_callback_provider_event"
        ),
        Index("ix_callback_correlation", "correlation_id", "created_at"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    provider_configuration_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("provider_configurations.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_id: Mapped[str] = mapped_column(String(200), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    provider_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    normalized_response: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    signature_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[CallbackStatus] = mapped_column(
        Enum(CallbackStatus, name="callback_status", native_enum=False), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ResultArtifact(IdentityMixin, Base):
    __tablename__ = "result_artifacts"

    execution_order_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("execution_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    execution_attempt_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("execution_attempts.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(100), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    stored_file_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("stored_files.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CostEntry(IdentityMixin, Base):
    __tablename__ = "cost_entries"
    __table_args__ = (
        CheckConstraint("amount_cents >= 0", name="ck_cost_entries_amount_nonnegative"),
        Index("ix_cost_entries_job_created", "job_id", "created_at"),
    )

    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_jobs.id", ondelete="CASCADE"), nullable=False
    )
    provider_call_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("provider_calls.id", ondelete="SET NULL")
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ApprovalRequest(IdentityMixin, Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        Index("ix_approval_requests_job_status", "job_id", "status"),
        Index(
            "ix_approval_requests_revision",
            "job_id",
            "job_revision",
            "invalidated_at",
        ),
    )

    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_jobs.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, name="approval_status"), nullable=False, default=ApprovalStatus.PENDING
    )
    requested_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    job_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    claimed_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    reason: Mapped[str | None] = mapped_column(Text)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobTask(IdentityMixin, Base):
    __tablename__ = "job_tasks"
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="ck_job_tasks_attempts_nonnegative"),
        CheckConstraint("max_attempts > 0", name="ck_job_tasks_max_attempts_positive"),
        Index("ix_job_tasks_claim", "status", "available_at", "created_at"),
    )

    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_jobs.id", ondelete="CASCADE"), nullable=False
    )
    task_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status"),
        nullable=False,
        default=TaskStatus.PENDING,
        server_default=TaskStatus.PENDING.value,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(200))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class IdempotencyRecord(IdentityMixin, Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "scope", "key", name="uq_idempotency_tenant_scope_key"),
        Index("ix_idempotency_created", "created_at"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(100), nullable=False)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StoredFile(IdentityMixin, Base):
    __tablename__ = "stored_files"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sha256", name="uq_stored_files_tenant_sha256"),
        UniqueConstraint("bucket", "object_key", name="uq_stored_files_object"),
        CheckConstraint("size_bytes > 0", name="ck_stored_files_size_positive"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    detected_mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bucket: Mapped[str] = mapped_column(String(100), nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class JobAttachment(IdentityMixin, Base):
    __tablename__ = "job_attachments"
    __table_args__ = (
        UniqueConstraint("job_id", "stored_file_id", name="uq_job_attachments_job_file"),
    )

    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("content_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stored_file_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("stored_files.id", ondelete="RESTRICT"), nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CaseRevision(IdentityMixin, Base):
    __tablename__ = "case_revisions"
    __table_args__ = (UniqueConstraint("job_id", "revision", name="uq_case_revision"),)

    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_jobs.id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    change_type: Mapped[str] = mapped_column(String(100), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InternalNote(IdentityMixin, Base):
    __tablename__ = "internal_notes"
    __table_args__ = (Index("ix_internal_notes_job_created", "job_id", "created_at"),)

    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    job_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    author_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ChecklistItem(IdentityMixin, Base):
    __tablename__ = "checklist_items"
    __table_args__ = (
        UniqueConstraint("job_id", "position", name="uq_checklist_job_position"),
        Index("ix_checklist_job_required", "job_id", "required"),
    )

    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    completed_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CaseEvidence(IdentityMixin, Base):
    __tablename__ = "case_evidence"
    __table_args__ = (Index("ix_case_evidence_job_created", "job_id", "created_at"),)

    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    job_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    stored_file_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("stored_files.id", ondelete="RESTRICT")
    )
    source: Mapped[str] = mapped_column(String(300), nullable=False)
    structured_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    verification_status: Mapped[EvidenceVerificationStatus] = mapped_column(
        Enum(EvidenceVerificationStatus, name="evidence_verification_status", native_enum=False),
        nullable=False,
        default=EvidenceVerificationStatus.UNVERIFIED,
        server_default=EvidenceVerificationStatus.UNVERIFIED.value,
    )
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Artifact(IdentityMixin, Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="ck_artifacts_size_nonnegative"),
        UniqueConstraint("bucket", "object_key", name="uq_artifacts_object"),
        Index("ix_artifacts_job_kind", "job_id", "kind"),
    )

    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_jobs.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[ArtifactKind] = mapped_column(Enum(ArtifactKind, name="artifact_kind"))
    bucket: Mapped[str] = mapped_column(String(100), nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


def _reject_audit_mutation(*_: object) -> None:
    raise ValueError("AuditEvent rows are immutable")


event.listen(AuditEvent, "before_update", _reject_audit_mutation)
event.listen(AuditEvent, "before_delete", _reject_audit_mutation)
event.listen(InternalNote, "before_update", _reject_audit_mutation)
event.listen(InternalNote, "before_delete", _reject_audit_mutation)
event.listen(CaseRevision, "before_update", _reject_audit_mutation)
event.listen(CaseRevision, "before_delete", _reject_audit_mutation)
event.listen(ExecutionRevision, "before_update", _reject_audit_mutation)
event.listen(ExecutionRevision, "before_delete", _reject_audit_mutation)
event.listen(DryRunResult, "before_update", _reject_audit_mutation)
event.listen(DryRunResult, "before_delete", _reject_audit_mutation)
