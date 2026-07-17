"""Phase 2 internal case-processing API."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.api.auth import (
    SessionContext,
    require_approval_actor,
    require_session_context,
    require_write_actor,
)
from mediaos.application.case_processing_service import CaseProcessingService
from mediaos.application.errors import JobNotFoundError
from mediaos.database import get_session
from mediaos.domain.actor import Actor
from mediaos.domain.enums import CasePriority, CaseStatus
from mediaos.domain.models import (
    ApprovalRequest,
    AuditEvent,
    CaseEvidence,
    CaseRevision,
    ChecklistItem,
    ContentJob,
    InternalNote,
    JobAttachment,
    StoredFile,
)

router = APIRouter(prefix="/api/v1/cases", tags=["phase-two"])
Session = Annotated[AsyncSession, Depends(get_session)]


class VersionBody(BaseModel):
    expected_version: int = Field(ge=1)


class CaseUpdateBody(VersionBody):
    category: str | None = Field(default=None, max_length=100)
    priority: CasePriority | None = None
    assigned_to: UUID | None = None
    due_at: datetime | None = None


class NoteBody(VersionBody):
    content: str = Field(min_length=1, max_length=5000)


class ChecklistBody(VersionBody):
    titles: list[str] = Field(min_length=1, max_length=20)


class ChecklistItemBody(VersionBody):
    completed: bool


class EvidenceBody(VersionBody):
    source: str = Field(min_length=1, max_length=300)
    stored_file_id: UUID | None = None
    structured_data: dict[str, Any] = Field(default_factory=dict)


class ApprovalResolutionBody(BaseModel):
    approved: bool
    reason: str | None = Field(default=None, max_length=2000)


class CloseBody(VersionBody):
    reason: str = Field(min_length=1, max_length=2000)


def _job_dict(job: ContentJob) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "tenant_id": str(job.tenant_id),
        "channel_id": str(job.channel_id),
        "title": job.title,
        "workflow_state": job.current_state.value,
        "business_status": job.business_status.value,
        "category": job.category,
        "priority": job.priority.value,
        "version": job.version,
        "assigned_to": str(job.assigned_to) if job.assigned_to else None,
        "claimed_by": str(job.claimed_by) if job.claimed_by else None,
        "claim_started_at": job.claim_started_at,
        "claim_expires_at": job.claim_expires_at,
        "claim_version": job.claim_version,
        "due_at": job.due_at,
        "completed_reason": job.completed_reason,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


@router.get("")
async def list_cases(
    session: Session,
    context: Annotated[SessionContext, Depends(require_session_context)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    queue: Literal["open", "mine", "unassigned", "due", "approval", "rejected", "completed"]
    | None = None,
    category: Annotated[str | None, Query(max_length=100)] = None,
    priority: CasePriority | None = None,
    status: CaseStatus | None = None,
    assigned_to: UUID | None = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
) -> dict[str, Any]:
    jobs, total = await CaseProcessingService(session).list_cases(
        actor=context.actor,
        page=page,
        page_size=page_size,
        queue=queue,
        category=category,
        priority=priority,
        status=status,
        assigned_to=assigned_to,
        search=search,
    )
    return {
        "items": [_job_dict(job) for job in jobs],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/{job_id}")
async def case_detail(
    job_id: UUID,
    session: Session,
    context: Annotated[SessionContext, Depends(require_session_context)],
) -> dict[str, Any]:
    job = await session.scalar(
        select(ContentJob).where(
            ContentJob.id == job_id, ContentJob.tenant_id == context.actor.tenant_id
        )
    )
    if job is None:
        raise JobNotFoundError("Case was not found in the authenticated tenant")
    attachments = (
        await session.execute(
            select(JobAttachment, StoredFile)
            .join(StoredFile, StoredFile.id == JobAttachment.stored_file_id)
            .where(JobAttachment.job_id == job.id)
            .order_by(JobAttachment.created_at)
        )
    ).all()
    notes = (
        await session.scalars(
            select(InternalNote)
            .where(InternalNote.job_id == job.id)
            .order_by(InternalNote.created_at)
        )
    ).all()
    checklist = (
        await session.scalars(
            select(ChecklistItem)
            .where(ChecklistItem.job_id == job.id)
            .order_by(ChecklistItem.position)
        )
    ).all()
    evidence = (
        await session.scalars(
            select(CaseEvidence)
            .where(CaseEvidence.job_id == job.id)
            .order_by(CaseEvidence.created_at)
        )
    ).all()
    approvals = (
        await session.scalars(
            select(ApprovalRequest)
            .where(ApprovalRequest.job_id == job.id)
            .order_by(ApprovalRequest.created_at)
        )
    ).all()
    revisions = (
        await session.scalars(
            select(CaseRevision)
            .where(CaseRevision.job_id == job.id)
            .order_by(CaseRevision.revision)
        )
    ).all()
    audits = (
        await session.scalars(
            select(AuditEvent).where(AuditEvent.job_id == job.id).order_by(AuditEvent.created_at)
        )
    ).all()
    return {
        **_job_dict(job),
        "attachments": [
            {
                "id": str(attachment.id),
                "stored_file_id": str(stored.id),
                "filename": attachment.original_filename,
                "sha256": stored.sha256,
                "mime_type": stored.detected_mime_type,
                "size_bytes": stored.size_bytes,
            }
            for attachment, stored in attachments
        ],
        "notes": [
            {
                "id": str(note.id),
                "revision": note.job_revision,
                "author_id": str(note.author_id),
                "content": note.content,
                "created_at": note.created_at,
            }
            for note in notes
        ],
        "checklist": [
            {
                "id": str(item.id),
                "title": item.title,
                "position": item.position,
                "required": item.required,
                "completed_by": str(item.completed_by) if item.completed_by else None,
                "completed_at": item.completed_at,
            }
            for item in checklist
        ],
        "evidence": [
            {
                "id": str(item.id),
                "revision": item.job_revision,
                "stored_file_id": str(item.stored_file_id) if item.stored_file_id else None,
                "source": item.source,
                "structured_data": item.structured_data,
                "verification_status": item.verification_status.value,
                "created_by": str(item.created_by),
                "created_at": item.created_at,
            }
            for item in evidence
        ],
        "approvals": [
            {
                "id": str(item.id),
                "revision": item.job_revision,
                "status": item.status.value,
                "requested_by": str(item.requested_by),
                "claimed_by": str(item.claimed_by) if item.claimed_by else None,
                "resolved_by": str(item.resolved_by) if item.resolved_by else None,
                "reason": item.reason,
                "invalidated_at": item.invalidated_at,
                "created_at": item.created_at,
            }
            for item in approvals
        ],
        "revisions": [
            {
                "id": str(item.id),
                "revision": item.revision,
                "actor_id": str(item.actor_id),
                "change_type": item.change_type,
                "snapshot": item.snapshot,
                "created_at": item.created_at,
            }
            for item in revisions
        ],
        "audit_events": [
            {
                "id": str(item.id),
                "event_type": item.event_type,
                "actor_id": str(item.actor_id),
                "payload": item.payload,
                "created_at": item.created_at,
            }
            for item in audits
        ],
    }


@router.post("/{job_id}/claim")
async def claim_case(
    job_id: UUID,
    body: VersionBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
) -> dict[str, Any]:
    return _job_dict(
        await CaseProcessingService(session).claim(
            actor=actor, job_id=job_id, expected_version=body.expected_version
        )
    )


@router.post("/{job_id}/claim/renew")
async def renew_case_claim(
    job_id: UUID,
    body: VersionBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
) -> dict[str, Any]:
    return _job_dict(
        await CaseProcessingService(session).renew_claim(
            actor=actor, job_id=job_id, expected_version=body.expected_version
        )
    )


@router.post("/{job_id}/update")
async def update_case(
    job_id: UUID,
    body: CaseUpdateBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
) -> dict[str, Any]:
    job = await CaseProcessingService(session).update_case(
        actor=actor,
        job_id=job_id,
        expected_version=body.expected_version,
        category=body.category,
        priority=body.priority,
        assigned_to=body.assigned_to,
        due_at=body.due_at,
    )
    return _job_dict(job)


@router.post("/{job_id}/notes")
async def add_note(
    job_id: UUID,
    body: NoteBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
) -> dict[str, Any]:
    note = await CaseProcessingService(session).add_note(
        actor=actor, job_id=job_id, expected_version=body.expected_version, content=body.content
    )
    return {"id": str(note.id), "revision": note.job_revision}


@router.post("/{job_id}/checklist")
async def generate_checklist(
    job_id: UUID,
    body: ChecklistBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
) -> dict[str, Any]:
    items = await CaseProcessingService(session).generate_checklist(
        actor=actor, job_id=job_id, expected_version=body.expected_version, titles=body.titles
    )
    return {"items": [{"id": str(item.id), "title": item.title} for item in items]}


@router.post("/{job_id}/checklist/{item_id}")
async def set_checklist_item(
    job_id: UUID,
    item_id: UUID,
    body: ChecklistItemBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
) -> dict[str, Any]:
    item = await CaseProcessingService(session).set_checklist_item(
        actor=actor,
        job_id=job_id,
        item_id=item_id,
        expected_version=body.expected_version,
        completed=body.completed,
    )
    return {"id": str(item.id), "completed": item.completed_at is not None}


@router.post("/{job_id}/evidence")
async def add_evidence(
    job_id: UUID,
    body: EvidenceBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
) -> dict[str, Any]:
    evidence = await CaseProcessingService(session).add_evidence(
        actor=actor,
        job_id=job_id,
        expected_version=body.expected_version,
        source=body.source,
        stored_file_id=body.stored_file_id,
        structured_data=body.structured_data,
    )
    return {"id": str(evidence.id), "revision": evidence.job_revision}


@router.post("/{job_id}/approval-requests")
async def request_approval(
    job_id: UUID,
    body: VersionBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
) -> dict[str, Any]:
    request = await CaseProcessingService(session).request_approval(
        actor=actor, job_id=job_id, expected_version=body.expected_version
    )
    return {"id": str(request.id), "revision": request.job_revision, "status": request.status.value}


@router.post("/approvals/{approval_id}/claim")
async def claim_approval(
    approval_id: UUID, session: Session, actor: Annotated[Actor, Depends(require_approval_actor)]
) -> dict[str, Any]:
    request = await CaseProcessingService(session).claim_approval(
        actor=actor, approval_id=approval_id
    )
    return {"id": str(request.id), "claimed_by": str(request.claimed_by)}


@router.post("/approvals/{approval_id}/resolve")
async def resolve_approval(
    approval_id: UUID,
    body: ApprovalResolutionBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_approval_actor)],
) -> dict[str, Any]:
    request = await CaseProcessingService(session).resolve_approval(
        actor=actor, approval_id=approval_id, approved=body.approved, reason=body.reason
    )
    return {"id": str(request.id), "status": request.status.value, "revision": request.job_revision}


@router.post("/{job_id}/close")
async def close_case(
    job_id: UUID,
    body: CloseBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
) -> dict[str, Any]:
    job = await CaseProcessingService(session).close_case(
        actor=actor, job_id=job_id, expected_version=body.expected_version, reason=body.reason
    )
    return _job_dict(job)
