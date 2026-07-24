"""Internal-only media verification, preview registration, and deletion worker."""

import hashlib
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.database import get_session_factory
from mediaos.domain.enums import (
    ActorType,
    MediaStatus,
    MediaStorageStatus,
    MediaTechnicalStatus,
    MediaVariantStatus,
    MediaVerificationStatus,
    RetentionStatus,
    RightsReviewStatus,
)
from mediaos.domain.models import (
    AuditEvent,
    MediaAsset,
    MediaCollectionItem,
    MediaFile,
    MediaRelation,
    MediaRights,
    MediaTask,
    MediaVariant,
    MediaVersion,
)
from mediaos.infrastructure.media_task_repository import MediaTaskRepository
from mediaos.infrastructure.object_storage import ObjectStorage

LOGGER = logging.getLogger(__name__)
MEDIA_WORKER_ID = "mediaos-media-worker"
MEDIA_WORKER_ACTOR_ID = UUID("00000000-0000-0000-0000-000000000003")


async def process_one_media_task(
    *, worker_id: str = MEDIA_WORKER_ID, storage: ObjectStorage | None = None
) -> bool:
    object_storage = storage or ObjectStorage()
    factory = get_session_factory()
    async with factory() as session:
        async with session.begin():
            repository = MediaTaskRepository(session)
            recovered = await repository.recover_stale()
            if recovered:
                LOGGER.warning("recovered %s stale media task claims", recovered)
            task = await repository.claim_next(worker_id=worker_id)
        if task is None:
            return False
        try:
            if task.task_type == "VERIFY_MEDIA":
                await _verify(task, object_storage)
            elif task.task_type == "REGISTER_PREVIEW":
                await _register_preview(task)
            elif task.task_type == "PURGE_MEDIA":
                await _purge(task, object_storage)
            else:
                raise ValueError(f"unsupported media task type: {task.task_type}")
        except ValueError as exc:
            async with session.begin():
                repository = MediaTaskRepository(session)
                failed = await repository.fail(task.id, error=str(exc), permanent=True)
                await _audit_task(session, task, "MEDIA_TASK_DEAD_LETTER", failed.last_error or "")
            return True
        except Exception as exc:
            async with session.begin():
                repository = MediaTaskRepository(session)
                failed = await repository.fail(task.id, error=str(exc), permanent=False)
                await _audit_task(
                    session,
                    task,
                    "MEDIA_TASK_RETRY"
                    if failed.status.value == "RETRY"
                    else "MEDIA_TASK_DEAD_LETTER",
                    failed.last_error or "",
                )
            LOGGER.warning("media task %s failed", task.id)
            return True
        async with session.begin():
            await MediaTaskRepository(session).complete(task.id)
            await _audit_task(session, task, "MEDIA_TASK_COMPLETED", "")
        return True


async def mark_expired_rights() -> int:
    now = datetime.now(UTC)
    count = 0
    async with get_session_factory()() as session, session.begin():
        rights = list(
            await session.scalars(
                select(MediaRights)
                .where(
                    MediaRights.review_status == RightsReviewStatus.APPROVED,
                    MediaRights.usage_end.is_not(None),
                    MediaRights.usage_end <= now,
                )
                .with_for_update(skip_locked=True)
            )
        )
        for item in rights:
            asset = await session.get(MediaAsset, item.media_asset_id)
            item.review_status = RightsReviewStatus.EXPIRED
            if asset is not None:
                asset.status = MediaStatus.RIGHTS_REVIEW
                asset.revision += 1
                session.add(
                    AuditEvent(
                        tenant_id=asset.tenant_id,
                        job_id=None,
                        media_asset_id=asset.id,
                        actor_id=MEDIA_WORKER_ACTOR_ID,
                        actor_type=ActorType.WORKER,
                        event_type="MEDIA_RIGHTS_EXPIRED",
                        payload={"rights_id": str(item.id)},
                    )
                )
            count += 1
    return count


async def _verify(task: MediaTask, storage: ObjectStorage) -> None:
    integrity_error: str | None = None
    async with get_session_factory()() as session, session.begin():
        version = await session.get(MediaVersion, task.media_version_id)
        if version is None:
            raise ValueError("media version for verification does not exist")
        media_file = await session.get(MediaFile, version.media_file_id)
        asset = await session.get(MediaAsset, task.media_asset_id)
        if media_file is None or asset is None:
            raise ValueError("media file or asset for verification does not exist")
        current_version = await session.scalar(
            select(MediaVersion).where(
                MediaVersion.media_asset_id == asset.id,
                MediaVersion.is_current.is_(True),
            )
        )
        affects_current = (
            current_version is not None and current_version.media_file_id == media_file.id
        )
        content = await storage.get_private(
            bucket=media_file.bucket, object_key=media_file.object_key
        )
        actual_hash = hashlib.sha256(content).hexdigest()
        if actual_hash != media_file.sha256 or len(content) != media_file.size_bytes:
            media_file.verification_status = MediaVerificationStatus.REJECTED
            media_file.quarantined = True
            if affects_current:
                asset.technical_status = MediaTechnicalStatus.QUARANTINED
                asset.status = MediaStatus.QUARANTINED
            integrity_error = "stored media integrity verification failed"
        else:
            media_file.verification_status = MediaVerificationStatus.VERIFIED
            media_file.storage_status = MediaStorageStatus.VERIFIED
            media_file.last_integrity_check_at = datetime.now(UTC)
            if affects_current:
                asset.storage_status = MediaStorageStatus.VERIFIED
            if affects_current and not media_file.quarantined:
                asset.technical_status = MediaTechnicalStatus.VERIFIED
                if asset.status == MediaStatus.TECHNICAL_REVIEW:
                    asset.status = MediaStatus.DRAFT
            existing_preview = await session.scalar(
                select(MediaVariant.id).where(
                    MediaVariant.source_version_id == version.id,
                    MediaVariant.variant_type == "PREVIEW",
                )
            )
            if existing_preview is None:
                session.add(
                    MediaTask(
                        tenant_id=asset.tenant_id,
                        media_asset_id=asset.id,
                        media_version_id=version.id,
                        task_type="REGISTER_PREVIEW",
                        payload={"external_effect": False},
                    )
                )
    if integrity_error is not None:
        raise ValueError(integrity_error)


async def _register_preview(task: MediaTask) -> None:
    async with get_session_factory()() as session, session.begin():
        version = await session.get(MediaVersion, task.media_version_id)
        if version is None:
            raise ValueError("media version for preview does not exist")
        existing = await session.scalar(
            select(MediaVariant).where(
                MediaVariant.source_version_id == version.id,
                MediaVariant.variant_type == "PREVIEW",
            )
        )
        if existing is None:
            session.add(
                MediaVariant(
                    source_version_id=version.id,
                    variant_type="PREVIEW",
                    technical_properties={
                        "authorized_route": True,
                        "uses_original_binary": True,
                        "external_processing": False,
                    },
                    media_file_id=version.media_file_id,
                    generation_status=MediaVariantStatus.READY,
                    generation_source="INTERNAL_SAFE_PREVIEW",
                    verification_result={"active_content": False},
                )
            )


async def _purge(task: MediaTask, storage: ObjectStorage) -> None:
    async with get_session_factory()() as session, session.begin():
        asset = await session.get(MediaAsset, task.media_asset_id)
        if asset is None:
            raise ValueError("media asset for deletion does not exist")
        if asset.retention_status != RetentionStatus.DELETION_APPROVED or asset.deletion_locked:
            raise ValueError("media asset is not approved for physical deletion")
        relations = await session.scalar(
            select(func.count(MediaRelation.id)).where(
                or_(
                    MediaRelation.source_asset_id == asset.id,
                    MediaRelation.target_asset_id == asset.id,
                )
            )
        )
        if relations:
            raise ValueError("media asset still has active relationships")
        collection_references = await session.scalar(
            select(func.count(MediaCollectionItem.id)).where(
                MediaCollectionItem.media_asset_id == asset.id
            )
        )
        proof_references = await session.scalar(
            select(func.count(MediaRights.id)).where(MediaRights.proof_media_asset_id == asset.id)
        )
        if collection_references or proof_references:
            raise ValueError("media asset still has active collection or rights references")
        versions = list(
            await session.scalars(
                select(MediaVersion).where(MediaVersion.media_asset_id == asset.id)
            )
        )
        purged_file_ids: list[str] = []
        for file_id in {version.media_file_id for version in versions}:
            other_references = await session.scalar(
                select(func.count(MediaVersion.id)).where(
                    MediaVersion.media_file_id == file_id,
                    MediaVersion.media_asset_id != asset.id,
                )
            )
            if other_references:
                continue
            media_file = await session.get(MediaFile, file_id)
            if media_file is not None and media_file.storage_status != MediaStorageStatus.DELETED:
                await storage.remove(bucket=media_file.bucket, object_key=media_file.object_key)
                media_file.storage_status = MediaStorageStatus.DELETED
                purged_file_ids.append(str(media_file.id))
        asset.status = MediaStatus.DELETED
        asset.retention_status = RetentionStatus.PURGED
        asset.storage_status = MediaStorageStatus.DELETED
        asset.revision += 1
        session.add(
            AuditEvent(
                tenant_id=asset.tenant_id,
                job_id=None,
                media_asset_id=asset.id,
                actor_id=MEDIA_WORKER_ACTOR_ID,
                actor_type=ActorType.WORKER,
                event_type="MEDIA_PURGED",
                payload={
                    "task_id": str(task.id),
                    "purged_file_ids": purged_file_ids,
                    "external_effect": False,
                },
            )
        )


async def _audit_task(session: AsyncSession, task: MediaTask, event_type: str, error: str) -> None:
    session.add(
        AuditEvent(
            tenant_id=task.tenant_id,
            job_id=None,
            media_asset_id=task.media_asset_id,
            actor_id=MEDIA_WORKER_ACTOR_ID,
            actor_type=ActorType.WORKER,
            event_type=event_type,
            payload={
                "task_id": str(task.id),
                "task_type": task.task_type,
                "attempts": task.attempts,
                "error": error,
                "external_effect": False,
            },
        )
    )
