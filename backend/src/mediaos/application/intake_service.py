"""Atomic tenant-scoped intake creation with private file deduplication."""

import hashlib
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.application.errors import JobNotFoundError, TenantBoundaryError
from mediaos.application.idempotency_service import (
    acquire_idempotency,
    canonical_request_hash,
    record_idempotency,
)
from mediaos.config import get_settings
from mediaos.domain.actor import Actor
from mediaos.domain.models import (
    AuditEvent,
    JobAttachment,
    JobTask,
    StoredFile,
)
from mediaos.infrastructure.object_storage import ObjectStorage, ValidatedUpload
from mediaos.infrastructure.repositories import ChannelRepository, ContentJobRepository


@dataclass(frozen=True, slots=True)
class IntakeResult:
    job_id: UUID
    attachment_id: UUID | None
    stored_file_id: UUID | None
    queue_task_id: UUID
    replayed: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": str(self.job_id),
            "attachment_id": str(self.attachment_id) if self.attachment_id else None,
            "stored_file_id": str(self.stored_file_id) if self.stored_file_id else None,
            "queue_task_id": str(self.queue_task_id),
            "replayed": self.replayed,
        }


class IntakeService:
    def __init__(self, session: AsyncSession, storage: ObjectStorage | None = None) -> None:
        self.session = session
        self.storage = storage or ObjectStorage()

    async def create(
        self,
        *,
        actor: Actor,
        idempotency_key: str,
        channel_id: UUID,
        title: str,
        budget_limit_cents: int,
        upload: ValidatedUpload | None,
        original_filename: str | None,
    ) -> IntakeResult:
        if actor.tenant_id is None:
            raise TenantBoundaryError("Authenticated actor has no tenant")
        file_sha = hashlib.sha256(upload.content).hexdigest() if upload else None
        request_hash = canonical_request_hash(
            {
                "channel_id": str(channel_id),
                "title": title,
                "budget_limit_cents": budget_limit_cents,
                "file_sha256": file_sha,
            }
        )
        uploaded_object: tuple[str, str] | None = None
        try:
            async with self.session.begin():
                existing = await acquire_idempotency(
                    self.session,
                    tenant_id=actor.tenant_id,
                    scope="CREATE_INTAKE",
                    key=idempotency_key,
                    request_hash=request_hash,
                )
                if existing is not None:
                    body = existing.response_body
                    return IntakeResult(
                        job_id=UUID(body["job_id"]),
                        attachment_id=UUID(body["attachment_id"])
                        if body.get("attachment_id")
                        else None,
                        stored_file_id=UUID(body["stored_file_id"])
                        if body.get("stored_file_id")
                        else None,
                        queue_task_id=UUID(body["queue_task_id"]),
                        replayed=True,
                    )
                channel = await ChannelRepository(self.session).get(
                    channel_id, tenant_id=actor.tenant_id
                )
                if channel is None:
                    raise JobNotFoundError("Channel was not found in the authenticated tenant")
                job = await ContentJobRepository(self.session).create(
                    tenant_id=actor.tenant_id,
                    channel_id=channel.id,
                    title=title,
                    budget_limit_cents=budget_limit_cents,
                )
                stored_file: StoredFile | None = None
                attachment: JobAttachment | None = None
                if upload is not None and file_sha is not None:
                    await self.session.execute(
                        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                        {"key": f"file:{actor.tenant_id}:{file_sha}"},
                    )
                    stored_file = await self.session.scalar(
                        select(StoredFile).where(
                            StoredFile.tenant_id == actor.tenant_id,
                            StoredFile.sha256 == file_sha,
                        )
                    )
                    if stored_file is None:
                        bucket = get_settings().mediaos_private_bucket
                        object_key = f"{actor.tenant_id}/{file_sha}/{uuid4()}"
                        await self.storage.put_private(
                            bucket=bucket,
                            object_key=object_key,
                            content=upload.content,
                            content_type=upload.detected_mime_type,
                        )
                        uploaded_object = (bucket, object_key)
                        stored_file = StoredFile(
                            tenant_id=actor.tenant_id,
                            created_by=actor.id,
                            sha256=file_sha,
                            detected_mime_type=upload.detected_mime_type,
                            size_bytes=len(upload.content),
                            bucket=bucket,
                            object_key=object_key,
                        )
                        self.session.add(stored_file)
                        await self.session.flush()
                    safe_name = PurePath(original_filename or "upload.bin").name[:255]
                    attachment = JobAttachment(
                        job_id=job.id,
                        stored_file_id=stored_file.id,
                        original_filename=safe_name or "upload.bin",
                    )
                    self.session.add(attachment)
                    await self.session.flush()
                task = JobTask(
                    job_id=job.id,
                    task_type="INTAKE_ACCEPTED",
                    payload={"tenant_id": str(actor.tenant_id)},
                    max_attempts=3,
                )
                self.session.add(task)
                await self.session.flush()
                self.session.add(
                    AuditEvent(
                        tenant_id=actor.tenant_id,
                        job_id=job.id,
                        actor_id=actor.id,
                        actor_type=actor.type,
                        event_type="INTAKE_CREATED",
                        payload={
                            "channel_id": str(channel.id),
                            "attachment_id": str(attachment.id) if attachment else None,
                            "stored_file_id": str(stored_file.id) if stored_file else None,
                            "queue_task_id": str(task.id),
                            "idempotency_key_hash": hashlib.sha256(
                                idempotency_key.encode("utf-8")
                            ).hexdigest(),
                        },
                    )
                )
                result = IntakeResult(
                    job_id=job.id,
                    attachment_id=attachment.id if attachment else None,
                    stored_file_id=stored_file.id if stored_file else None,
                    queue_task_id=task.id,
                    replayed=False,
                )
                record_idempotency(
                    self.session,
                    tenant_id=actor.tenant_id,
                    scope="CREATE_INTAKE",
                    key=idempotency_key,
                    request_hash=request_hash,
                    response_status=201,
                    response_body=result.as_dict(),
                )
            return result
        except Exception:
            if uploaded_object is not None:
                await self.storage.remove(bucket=uploaded_object[0], object_key=uploaded_object[1])
            raise
