"""Phase 1 authenticated intake and private download API."""

from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.api.auth import SessionContext, require_session_context, require_write_actor
from mediaos.application.errors import (
    StoredFileNotFoundError,
    TenantBoundaryError,
)
from mediaos.application.intake_service import IntakeService
from mediaos.config import get_settings
from mediaos.database import get_session
from mediaos.domain.actor import Actor
from mediaos.domain.models import AuditEvent, ContentJob, JobAttachment, StoredFile
from mediaos.infrastructure.object_storage import ObjectStorage, validate_upload

router = APIRouter(prefix="/api/v1", tags=["phase-one"])
Session = Annotated[AsyncSession, Depends(get_session)]


class IntakeResponse(BaseModel):
    job_id: UUID
    attachment_id: UUID | None
    stored_file_id: UUID | None
    queue_task_id: UUID
    replayed: bool


@router.post("/intakes", response_model=IntakeResponse, status_code=status.HTTP_201_CREATED)
async def create_intake(
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    channel_id: Annotated[UUID, Form()],
    title: Annotated[str, Form(min_length=1, max_length=300)],
    budget_limit_cents: Annotated[int, Form(ge=0)],
    upload: Annotated[UploadFile | None, File()] = None,
) -> IntakeResponse:
    validated = None
    filename = None
    if upload is not None:
        content = await upload.read(get_settings().mediaos_upload_max_bytes + 1)
        validated = validate_upload(content, upload.content_type)
        filename = upload.filename
    result = await IntakeService(session).create(
        actor=actor,
        idempotency_key=idempotency_key,
        channel_id=channel_id,
        title=title,
        budget_limit_cents=budget_limit_cents,
        upload=validated,
        original_filename=filename,
    )
    return IntakeResponse(**result.as_dict())


@router.get("/files/{stored_file_id}/download")
async def download_file(
    stored_file_id: UUID,
    session: Session,
    context: Annotated[SessionContext, Depends(require_session_context)],
) -> Response:
    tenant_id = context.actor.tenant_id
    if tenant_id is None:
        raise TenantBoundaryError("Authenticated actor has no tenant")
    result = await session.execute(
        select(StoredFile, JobAttachment, ContentJob)
        .join(JobAttachment, JobAttachment.stored_file_id == StoredFile.id)
        .join(ContentJob, ContentJob.id == JobAttachment.job_id)
        .where(StoredFile.id == stored_file_id, StoredFile.tenant_id == tenant_id)
        .order_by(JobAttachment.created_at)
        .limit(1)
    )
    row = result.one_or_none()
    if row is None:
        raise StoredFileNotFoundError("Stored file was not found in the authenticated tenant")
    stored_file, attachment, job = row
    content = await ObjectStorage().get_private(
        bucket=stored_file.bucket, object_key=stored_file.object_key
    )
    session.add(
        AuditEvent(
            tenant_id=tenant_id,
            job_id=job.id,
            actor_id=context.actor.id,
            actor_type=context.actor.type,
            event_type="FILE_DOWNLOADED",
            payload={"stored_file_id": str(stored_file.id)},
        )
    )
    await session.commit()
    encoded_name = quote(attachment.original_filename, safe="")
    return Response(
        content=content,
        media_type=stored_file.detected_mime_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )
