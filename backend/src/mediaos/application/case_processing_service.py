"""Tenant-safe, revision-bound internal case processing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.application.errors import (
    ApprovalConflictError,
    AuthorizationError,
    ChecklistIncompleteError,
    ClaimConflictError,
    JobNotFoundError,
    StoredFileNotFoundError,
    TenantBoundaryError,
    VersionConflictError,
)
from mediaos.domain.actor import Actor
from mediaos.domain.enums import (
    ActorType,
    ApprovalStatus,
    CasePriority,
    CaseStatus,
    EvidenceVerificationStatus,
    ExecutionStatus,
    OutboxStatus,
    RoleName,
    TechnicalApprovalStatus,
)
from mediaos.domain.models import (
    ApprovalRequest,
    AuditEvent,
    CaseEvidence,
    CaseRevision,
    ChecklistItem,
    ContentJob,
    ExecutionOrder,
    InternalNote,
    JobAttachment,
    JobTask,
    OutboxEvent,
    StoredFile,
    TechnicalApproval,
    User,
)

CLAIM_MINUTES = 15


def case_snapshot(job: ContentJob) -> dict[str, Any]:
    return {
        "title": job.title,
        "category": job.category,
        "priority": job.priority.value,
        "business_status": job.business_status.value,
        "assigned_to": str(job.assigned_to) if job.assigned_to else None,
        "due_at": job.due_at.isoformat() if job.due_at else None,
        "completed_reason": job.completed_reason,
    }


class CaseProcessingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_cases(
        self,
        *,
        actor: Actor,
        page: int,
        page_size: int,
        queue: str | None = None,
        category: str | None = None,
        priority: CasePriority | None = None,
        status: CaseStatus | None = None,
        assigned_to: UUID | None = None,
        search: str | None = None,
    ) -> tuple[list[ContentJob], int]:
        tenant_id = self._tenant(actor)
        statement: Select[tuple[ContentJob]] = select(ContentJob).where(
            ContentJob.tenant_id == tenant_id
        )
        now = datetime.now(UTC)
        if queue == "mine":
            statement = statement.where(ContentJob.assigned_to == actor.id)
        elif queue == "unassigned":
            statement = statement.where(ContentJob.assigned_to.is_(None))
        elif queue == "due":
            statement = statement.where(ContentJob.due_at.is_not(None), ContentJob.due_at <= now)
        elif queue == "approval":
            statement = statement.where(ContentJob.business_status == CaseStatus.AWAITING_APPROVAL)
        elif queue == "rejected":
            statement = statement.where(ContentJob.business_status == CaseStatus.REJECTED)
        elif queue == "completed":
            statement = statement.where(ContentJob.business_status == CaseStatus.COMPLETED)
        elif queue == "open":
            statement = statement.where(
                ContentJob.business_status.not_in([CaseStatus.COMPLETED, CaseStatus.REJECTED])
            )
        if category:
            statement = statement.where(ContentJob.category == category)
        if priority:
            statement = statement.where(ContentJob.priority == priority)
        if status:
            statement = statement.where(ContentJob.business_status == status)
        if assigned_to:
            statement = statement.where(ContentJob.assigned_to == assigned_to)
        if search:
            term = f"%{search.strip()}%"
            statement = statement.where(
                or_(ContentJob.title.ilike(term), ContentJob.category.ilike(term))
            )
        total = int(
            await self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        )
        jobs = list(
            (
                await self.session.scalars(
                    statement.order_by(ContentJob.created_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return jobs, total

    async def claim(self, *, actor: Actor, job_id: UUID, expected_version: int) -> ContentJob:
        async with self.session.begin():
            job = await self._locked_job(actor, job_id)
            self._expect_version(job, expected_version)
            if job.business_status == CaseStatus.COMPLETED:
                raise ApprovalConflictError("Completed cases cannot be claimed or changed")
            now = datetime.now(UTC)
            previous_owner = job.claimed_by
            if (
                job.claimed_by
                and job.claimed_by != actor.id
                and job.claim_expires_at
                and job.claim_expires_at > now
            ):
                raise ClaimConflictError(
                    "Case is actively claimed by another user",
                    details={"claim_expires_at": job.claim_expires_at.isoformat()},
                )
            event_type = (
                "CASE_CLAIM_TAKEN_OVER"
                if previous_owner is not None and previous_owner != actor.id
                else "CASE_CLAIMED"
            )
            job.claimed_by = actor.id
            job.assigned_to = actor.id
            job.claim_started_at = now
            job.claim_expires_at = now + timedelta(minutes=CLAIM_MINUTES)
            job.claim_version = job.version
            if job.business_status == CaseStatus.OPEN:
                job.business_status = CaseStatus.IN_PROGRESS
            self._audit(job, actor, event_type, {"claim_version": job.version})
        await self.session.refresh(job)
        return job

    async def renew_claim(self, *, actor: Actor, job_id: UUID, expected_version: int) -> ContentJob:
        async with self.session.begin():
            job = await self._locked_job(actor, job_id)
            self._expect_version(job, expected_version)
            self._require_claim(job, actor)
            job.claim_expires_at = datetime.now(UTC) + timedelta(minutes=CLAIM_MINUTES)
            self._audit(job, actor, "CASE_CLAIM_RENEWED", {"claim_version": job.version})
        await self.session.refresh(job)
        return job

    async def update_case(
        self,
        *,
        actor: Actor,
        job_id: UUID,
        expected_version: int,
        category: str | None,
        priority: CasePriority | None,
        assigned_to: UUID | None,
        due_at: datetime | None,
        due_at_supplied: bool,
    ) -> ContentJob:
        async with self.session.begin():
            job = await self._locked_job(actor, job_id)
            self._expect_version(job, expected_version)
            self._require_claim(job, actor)
            if assigned_to is not None:
                target = await self.session.get(User, assigned_to)
                if target is None or target.tenant_id != job.tenant_id or not target.active:
                    raise TenantBoundaryError("Assignee is not active in the authenticated tenant")
                job.assigned_to = assigned_to
            if category is not None:
                job.category = category.strip()
            if priority is not None:
                job.priority = priority
            if due_at_supplied:
                job.due_at = due_at
            await self._material_change(job, actor, "CASE_UPDATED")
        await self.session.refresh(job)
        return job

    async def add_note(
        self, *, actor: Actor, job_id: UUID, expected_version: int, content: str
    ) -> InternalNote:
        async with self.session.begin():
            job = await self._locked_job(actor, job_id)
            self._expect_version(job, expected_version)
            self._require_claim(job, actor)
            await self._material_change(job, actor, "INTERNAL_NOTE_ADDED")
            note = InternalNote(
                job_id=job.id, job_revision=job.version, author_id=actor.id, content=content.strip()
            )
            self.session.add(note)
            await self.session.flush()
            self._audit(
                job,
                actor,
                "INTERNAL_NOTE_ADDED",
                {"note_id": str(note.id), "revision": job.version},
            )
        return note

    async def generate_checklist(
        self, *, actor: Actor, job_id: UUID, expected_version: int, titles: list[str]
    ) -> list[ChecklistItem]:
        async with self.session.begin():
            job = await self._locked_job(actor, job_id)
            self._expect_version(job, expected_version)
            self._require_claim(job, actor)
            existing = int(
                await self.session.scalar(
                    select(func.count(ChecklistItem.id)).where(ChecklistItem.job_id == job.id)
                )
                or 0
            )
            if existing:
                raise VersionConflictError("Checklist already exists")
            items = [
                ChecklistItem(job_id=job.id, title=title.strip(), position=index, required=True)
                for index, title in enumerate(titles, start=1)
            ]
            self.session.add_all(items)
            await self._material_change(job, actor, "CHECKLIST_GENERATED")
            task = JobTask(
                job_id=job.id,
                task_type="CHECKLIST_GENERATED",
                payload={"revision": job.version, "items": len(items)},
            )
            self.session.add(task)
            await self.session.flush()
            self._audit(
                job, actor, "CHECKLIST_GENERATED", {"items": len(items), "task_id": str(task.id)}
            )
        return items

    async def set_checklist_item(
        self,
        *,
        actor: Actor,
        job_id: UUID,
        item_id: UUID,
        expected_version: int,
        completed: bool,
    ) -> ChecklistItem:
        async with self.session.begin():
            job = await self._locked_job(actor, job_id)
            self._expect_version(job, expected_version)
            self._require_claim(job, actor)
            item = await self.session.scalar(
                select(ChecklistItem)
                .where(ChecklistItem.id == item_id, ChecklistItem.job_id == job.id)
                .with_for_update()
            )
            if item is None:
                raise JobNotFoundError("Checklist item was not found")
            item.completed_by = actor.id if completed else None
            item.completed_at = datetime.now(UTC) if completed else None
            await self._material_change(job, actor, "CHECKLIST_ITEM_CHANGED")
            self._audit(
                job,
                actor,
                "CHECKLIST_ITEM_CHANGED",
                {"item_id": str(item.id), "completed": completed},
            )
        return item

    async def add_evidence(
        self,
        *,
        actor: Actor,
        job_id: UUID,
        expected_version: int,
        source: str,
        stored_file_id: UUID | None,
        structured_data: dict[str, Any],
    ) -> CaseEvidence:
        async with self.session.begin():
            job = await self._locked_job(actor, job_id)
            self._expect_version(job, expected_version)
            self._require_claim(job, actor)
            if stored_file_id:
                stored_file = await self.session.get(StoredFile, stored_file_id)
                attached = await self.session.scalar(
                    select(JobAttachment.id).where(
                        JobAttachment.job_id == job.id,
                        JobAttachment.stored_file_id == stored_file_id,
                    )
                )
                if (
                    stored_file is None
                    or stored_file.tenant_id != job.tenant_id
                    or attached is None
                ):
                    raise StoredFileNotFoundError("Evidence file is not attached to this case")
            await self._material_change(job, actor, "EVIDENCE_ADDED")
            evidence = CaseEvidence(
                job_id=job.id,
                job_revision=job.version,
                stored_file_id=stored_file_id,
                source=source.strip(),
                structured_data=structured_data,
                verification_status=EvidenceVerificationStatus.UNVERIFIED,
                created_by=actor.id,
            )
            self.session.add(evidence)
            await self.session.flush()
            self._audit(
                job,
                actor,
                "EVIDENCE_ADDED",
                {"evidence_id": str(evidence.id), "revision": job.version},
            )
        return evidence

    async def request_approval(
        self, *, actor: Actor, job_id: UUID, expected_version: int
    ) -> ApprovalRequest:
        async with self.session.begin():
            job = await self._locked_job(actor, job_id)
            self._expect_version(job, expected_version)
            self._require_claim(job, actor)
            await self._require_complete_checklist(job.id)
            pending = await self.session.scalar(
                select(ApprovalRequest.id).where(
                    ApprovalRequest.job_id == job.id,
                    ApprovalRequest.status == ApprovalStatus.PENDING,
                    ApprovalRequest.invalidated_at.is_(None),
                )
            )
            if pending:
                raise ApprovalConflictError("An approval request is already pending")
            request = ApprovalRequest(
                job_id=job.id,
                job_revision=job.version,
                requested_by=actor.id,
                status=ApprovalStatus.PENDING,
            )
            job.business_status = CaseStatus.AWAITING_APPROVAL
            self.session.add(request)
            await self.session.flush()
            self._audit(
                job,
                actor,
                "APPROVAL_REQUESTED",
                {"approval_id": str(request.id), "revision": job.version},
            )
        return request

    async def claim_approval(self, *, actor: Actor, approval_id: UUID) -> ApprovalRequest:
        self._require_human_reviewer(actor)
        async with self.session.begin():
            request, job = await self._locked_approval(actor, approval_id)
            self._validate_approval_actor(request, job, actor)
            if request.claimed_by not in (None, actor.id):
                raise ApprovalConflictError("Approval is claimed by another reviewer")
            request.claimed_by = actor.id
            request.claimed_at = datetime.now(UTC)
            self._audit(
                job,
                actor,
                "APPROVAL_CLAIMED",
                {"approval_id": str(request.id), "revision": request.job_revision},
            )
        return request

    async def resolve_approval(
        self, *, actor: Actor, approval_id: UUID, approved: bool, reason: str | None
    ) -> ApprovalRequest:
        self._require_human_reviewer(actor)
        async with self.session.begin():
            request, job = await self._locked_approval(actor, approval_id)
            self._validate_approval_actor(request, job, actor)
            if request.claimed_by not in (None, actor.id):
                raise ApprovalConflictError("Approval is claimed by another reviewer")
            if not approved and not (reason or "").strip():
                raise ApprovalConflictError("A rejection reason is required")
            await self._require_complete_checklist(job.id)
            request.claimed_by = actor.id
            request.claimed_at = request.claimed_at or datetime.now(UTC)
            request.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
            request.resolved_by = actor.id
            request.resolved_at = datetime.now(UTC)
            request.reason = reason.strip() if reason else None
            job.business_status = CaseStatus.APPROVED if approved else CaseStatus.REJECTED
            self._audit(
                job,
                actor,
                "APPROVAL_GRANTED" if approved else "APPROVAL_REJECTED",
                {
                    "approval_id": str(request.id),
                    "revision": request.job_revision,
                    "reason": request.reason,
                },
            )
        return request

    async def close_case(
        self, *, actor: Actor, job_id: UUID, expected_version: int, reason: str
    ) -> ContentJob:
        async with self.session.begin():
            job = await self._locked_job(actor, job_id)
            self._expect_version(job, expected_version)
            self._require_claim(job, actor)
            approved = await self.session.scalar(
                select(ApprovalRequest.id).where(
                    ApprovalRequest.job_id == job.id,
                    ApprovalRequest.job_revision == job.version,
                    ApprovalRequest.status == ApprovalStatus.APPROVED,
                    ApprovalRequest.invalidated_at.is_(None),
                )
            )
            if not approved:
                raise ApprovalConflictError("Current case revision is not approved")
            job.business_status = CaseStatus.COMPLETED
            job.completed_reason = reason.strip()
            job.claimed_by = None
            job.claim_started_at = None
            job.claim_expires_at = None
            job.claim_version = None
            self._audit(
                job,
                actor,
                "CASE_COMPLETED",
                {"revision": job.version, "reason": job.completed_reason},
            )
        await self.session.refresh(job)
        return job

    async def _material_change(self, job: ContentJob, actor: Actor, change_type: str) -> None:
        job.version += 1
        job.claim_version = job.version
        job.last_material_actor_id = actor.id
        if job.business_status in {
            CaseStatus.AWAITING_APPROVAL,
            CaseStatus.APPROVED,
            CaseStatus.REJECTED,
        }:
            job.business_status = CaseStatus.IN_PROGRESS
        invalidated = await self.session.execute(
            update(ApprovalRequest)
            .where(
                ApprovalRequest.job_id == job.id,
                ApprovalRequest.invalidated_at.is_(None),
            )
            .values(invalidated_at=datetime.now(UTC))
        )
        invalidated_count = int(getattr(invalidated, "rowcount", 0) or 0)
        technical = await self.session.execute(
            update(TechnicalApproval)
            .where(
                TechnicalApproval.job_id == job.id,
                TechnicalApproval.job_revision < job.version,
                TechnicalApproval.invalidated_at.is_(None),
            )
            .values(
                status=TechnicalApprovalStatus.INVALIDATED,
                invalidated_at=datetime.now(UTC),
            )
        )
        pending_execution_ids = list(
            (
                await self.session.scalars(
                    select(ExecutionOrder.id).where(
                        ExecutionOrder.job_id == job.id,
                        ExecutionOrder.job_revision < job.version,
                        ExecutionOrder.status.in_(
                            [ExecutionStatus.VALIDATED, ExecutionStatus.QUEUED]
                        ),
                    )
                )
            ).all()
        )
        if pending_execution_ids:
            await self.session.execute(
                update(ExecutionOrder)
                .where(ExecutionOrder.id.in_(pending_execution_ids))
                .values(
                    status=ExecutionStatus.INVALIDATED,
                    invalidated_at=datetime.now(UTC),
                )
            )
            await self.session.execute(
                update(OutboxEvent)
                .where(
                    OutboxEvent.execution_order_id.in_(pending_execution_ids),
                    OutboxEvent.status.in_([OutboxStatus.PENDING, OutboxStatus.RETRY]),
                )
                .values(status=OutboxStatus.INVALIDATED)
            )
        technical_count = int(getattr(technical, "rowcount", 0) or 0)
        self.session.add(
            CaseRevision(
                job_id=job.id,
                revision=job.version,
                actor_id=actor.id,
                change_type=change_type,
                snapshot=case_snapshot(job),
            )
        )
        if invalidated_count:
            self._audit(
                job,
                actor,
                "APPROVAL_INVALIDATED",
                {"new_revision": job.version, "invalidated_requests": invalidated_count},
            )
        if technical_count or pending_execution_ids:
            self._audit(
                job,
                actor,
                "PROVIDER_EXECUTION_GATE_INVALIDATED",
                {
                    "new_revision": job.version,
                    "technical_approvals": technical_count,
                    "pending_executions": len(pending_execution_ids),
                },
            )

    async def _locked_job(self, actor: Actor, job_id: UUID) -> ContentJob:
        job = await self.session.scalar(
            select(ContentJob)
            .where(ContentJob.id == job_id, ContentJob.tenant_id == self._tenant(actor))
            .with_for_update()
        )
        if job is None:
            raise JobNotFoundError("Case was not found in the authenticated tenant")
        return job

    async def _locked_approval(
        self, actor: Actor, approval_id: UUID
    ) -> tuple[ApprovalRequest, ContentJob]:
        row = (
            await self.session.execute(
                select(ApprovalRequest, ContentJob)
                .join(ContentJob, ContentJob.id == ApprovalRequest.job_id)
                .where(
                    ApprovalRequest.id == approval_id,
                    ContentJob.tenant_id == self._tenant(actor),
                )
                .with_for_update()
            )
        ).one_or_none()
        if row is None:
            raise JobNotFoundError("Approval request was not found")
        return row[0], row[1]

    @staticmethod
    def _expect_version(job: ContentJob, expected_version: int) -> None:
        if job.version != expected_version:
            raise VersionConflictError(
                "Case revision is stale",
                details={"expected": expected_version, "current": job.version},
            )

    @staticmethod
    def _require_claim(job: ContentJob, actor: Actor) -> None:
        if job.business_status == CaseStatus.COMPLETED:
            raise ApprovalConflictError("Completed cases cannot be changed")
        now = datetime.now(UTC)
        if job.claimed_by != actor.id or not job.claim_expires_at or job.claim_expires_at <= now:
            raise ClaimConflictError("An active claim owned by the actor is required")

    async def _require_complete_checklist(self, job_id: UUID) -> None:
        counts = (
            await self.session.execute(
                select(
                    func.count(ChecklistItem.id),
                    func.count(ChecklistItem.id).filter(ChecklistItem.completed_at.is_not(None)),
                ).where(ChecklistItem.job_id == job_id, ChecklistItem.required.is_(True))
            )
        ).one()
        if counts[0] == 0 or counts[0] != counts[1]:
            raise ChecklistIncompleteError("All required checklist items must be complete")

    @staticmethod
    def _require_human_reviewer(actor: Actor) -> None:
        if actor.type != ActorType.USER or actor.roles.isdisjoint(
            {RoleName.ADMIN, RoleName.REVIEWER}
        ):
            raise AuthorizationError("A human Admin or Reviewer is required")

    @staticmethod
    def _validate_approval_actor(request: ApprovalRequest, job: ContentJob, actor: Actor) -> None:
        if request.invalidated_at is not None or request.status != ApprovalStatus.PENDING:
            raise ApprovalConflictError("Approval request is no longer active")
        if request.job_revision != job.version:
            raise ApprovalConflictError("Approval request targets a stale case revision")
        if actor.id in {request.requested_by, job.last_material_actor_id}:
            raise ApprovalConflictError(
                "Self-approval of a materially edited revision is forbidden"
            )

    @staticmethod
    def _tenant(actor: Actor) -> UUID:
        if actor.tenant_id is None:
            raise TenantBoundaryError("Authenticated actor has no tenant")
        return actor.tenant_id

    def _audit(
        self, job: ContentJob, actor: Actor, event_type: str, payload: dict[str, Any]
    ) -> None:
        self.session.add(
            AuditEvent(
                tenant_id=job.tenant_id,
                job_id=job.id,
                actor_id=actor.id,
                actor_type=actor.type,
                event_type=event_type,
                payload=payload,
            )
        )
