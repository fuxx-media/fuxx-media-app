"""Tenant-scoped, revision-safe media lifecycle application service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Any
from uuid import UUID

from sqlalchemy import String, cast, delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.application.errors import (
    AuthorizationError,
    MediaConflictError,
    MediaDeletionError,
    MediaNotFoundError,
    MediaRightsError,
    TenantBoundaryError,
    VersionConflictError,
)
from mediaos.application.idempotency_service import (
    acquire_idempotency,
    canonical_request_hash,
    record_idempotency,
)
from mediaos.application.media_validation import ValidatedMedia
from mediaos.config import get_settings
from mediaos.domain.actor import Actor
from mediaos.domain.enums import (
    MediaApprovalStatus,
    MediaCollectionStatus,
    MediaCollectionVisibility,
    MediaRelationType,
    MediaStatus,
    MediaStorageStatus,
    MediaTechnicalStatus,
    MediaVariantStatus,
    MediaVerificationStatus,
    RetentionStatus,
    RightsReviewStatus,
    TaskStatus,
)
from mediaos.domain.models import (
    AuditEvent,
    MediaApproval,
    MediaAsset,
    MediaAssetTag,
    MediaCategory,
    MediaCollection,
    MediaCollectionHistory,
    MediaCollectionItem,
    MediaDeletionRequest,
    MediaFile,
    MediaMetadata,
    MediaRelation,
    MediaRights,
    MediaTag,
    MediaTask,
    MediaVariant,
    MediaVersion,
)
from mediaos.infrastructure.object_storage import ObjectStorage


@dataclass(frozen=True, slots=True)
class MediaUploadResult:
    asset_id: UUID
    version_id: UUID
    file_id: UUID
    duplicate_binary: bool
    quarantined: bool
    replayed: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset_id": str(self.asset_id),
            "version_id": str(self.version_id),
            "file_id": str(self.file_id),
            "duplicate_binary": self.duplicate_binary,
            "quarantined": self.quarantined,
            "replayed": self.replayed,
        }


class MediaService:
    def __init__(self, session: AsyncSession, storage: ObjectStorage | None = None) -> None:
        self.session = session
        self.storage = storage or ObjectStorage()

    async def create_asset(
        self,
        *,
        actor: Actor,
        idempotency_key: str,
        title: str,
        description: str | None,
        upload: ValidatedMedia,
        original_filename: str | None,
    ) -> MediaUploadResult:
        tenant_id = self._tenant(actor)
        request_hash = canonical_request_hash(
            {
                "title": title.strip(),
                "description": description or "",
                "sha256": upload.sha256,
            }
        )
        uploaded: tuple[str, str] | None = None
        try:
            async with self.session.begin():
                existing = await acquire_idempotency(
                    self.session,
                    tenant_id=tenant_id,
                    scope="CREATE_MEDIA_ASSET",
                    key=idempotency_key,
                    request_hash=request_hash,
                )
                if existing is not None:
                    return self._upload_result(existing.response_body, replayed=True)
                asset = MediaAsset(
                    tenant_id=tenant_id,
                    title=title.strip(),
                    description=(description or "").strip() or None,
                    media_type=upload.media_type,
                    status=(
                        MediaStatus.QUARANTINED
                        if upload.quarantined
                        else MediaStatus.TECHNICAL_REVIEW
                    ),
                    technical_status=(
                        MediaTechnicalStatus.QUARANTINED
                        if upload.quarantined
                        else MediaTechnicalStatus.VERIFIED
                    ),
                    storage_status=MediaStorageStatus.STORED,
                    current_version_number=1,
                    created_by=actor.id,
                    assigned_to=actor.id,
                )
                self.session.add(asset)
                await self.session.flush()
                media_file, duplicate = await self._store_file(actor, upload)
                if not duplicate:
                    uploaded = (media_file.bucket, media_file.object_key)
                version = self._new_version(
                    actor=actor,
                    asset=asset,
                    media_file=media_file,
                    upload=upload,
                    original_filename=original_filename,
                    change_reason="Erstversion",
                    version_number=1,
                )
                self.session.add(version)
                await self.session.flush()
                self.session.add(
                    MediaMetadata(
                        media_version_id=version.id,
                        technical=upload.technical_metadata,
                        business={},
                        custom={},
                        system_generated={
                            "validation_issues": list(upload.validation_issues),
                            "duplicate_binary": duplicate,
                        },
                    )
                )
                self._queue(asset, version, "VERIFY_MEDIA")
                self._audit(
                    actor,
                    asset,
                    "MEDIA_ASSET_CREATED",
                    {
                        "version_id": str(version.id),
                        "sha256": upload.sha256,
                        "duplicate_binary": duplicate,
                        "quarantined": upload.quarantined,
                    },
                )
                result = MediaUploadResult(
                    asset.id, version.id, media_file.id, duplicate, upload.quarantined, False
                )
                record_idempotency(
                    self.session,
                    tenant_id=tenant_id,
                    scope="CREATE_MEDIA_ASSET",
                    key=idempotency_key,
                    request_hash=request_hash,
                    response_status=201,
                    response_body=result.as_dict(),
                )
            return result
        except Exception:
            if uploaded is not None:
                await self.storage.remove(bucket=uploaded[0], object_key=uploaded[1])
            raise

    async def add_version(
        self,
        *,
        actor: Actor,
        asset_id: UUID,
        expected_revision: int,
        idempotency_key: str,
        reason: str,
        upload: ValidatedMedia,
        original_filename: str | None,
    ) -> MediaUploadResult:
        tenant_id = self._tenant(actor)
        request_hash = canonical_request_hash(
            {
                "asset_id": str(asset_id),
                "expected_revision": expected_revision,
                "reason": reason,
                "sha256": upload.sha256,
            }
        )
        uploaded: tuple[str, str] | None = None
        try:
            async with self.session.begin():
                existing = await acquire_idempotency(
                    self.session,
                    tenant_id=tenant_id,
                    scope="CREATE_MEDIA_VERSION",
                    key=idempotency_key,
                    request_hash=request_hash,
                )
                if existing is not None:
                    return self._upload_result(existing.response_body, replayed=True)
                asset = await self._asset(tenant_id, asset_id, locked=True)
                self._expect_revision(asset, expected_revision)
                previous = await self.session.scalar(
                    select(MediaVersion).where(
                        MediaVersion.media_asset_id == asset.id, MediaVersion.is_current.is_(True)
                    )
                )
                media_file, duplicate = await self._store_file(actor, upload)
                if not duplicate:
                    uploaded = (media_file.bucket, media_file.object_key)
                next_number = asset.current_version_number + 1
                version = self._new_version(
                    actor=actor,
                    asset=asset,
                    media_file=media_file,
                    upload=upload,
                    original_filename=original_filename,
                    change_reason=reason.strip(),
                    version_number=next_number,
                )
                self.session.add(version)
                await self.session.flush()
                if previous is not None:
                    previous.is_current = False
                    previous.superseded_by_id = version.id
                asset.current_version_number = next_number
                asset.revision += 1
                asset.media_type = upload.media_type
                asset.technical_status = (
                    MediaTechnicalStatus.QUARANTINED
                    if upload.quarantined
                    else MediaTechnicalStatus.VERIFIED
                )
                asset.status = (
                    MediaStatus.QUARANTINED if upload.quarantined else MediaStatus.TECHNICAL_REVIEW
                )
                asset.approval_status = MediaApprovalStatus.NOT_REQUESTED
                self.session.add(
                    MediaMetadata(
                        media_version_id=version.id,
                        technical=upload.technical_metadata,
                        business={},
                        custom={},
                        system_generated={
                            "validation_issues": list(upload.validation_issues),
                            "duplicate_binary": duplicate,
                        },
                    )
                )
                self._queue(asset, version, "VERIFY_MEDIA")
                self._audit(
                    actor,
                    asset,
                    "MEDIA_VERSION_CREATED",
                    {
                        "old_version": previous.version_number if previous else None,
                        "new_version": next_number,
                        "reason": reason.strip(),
                        "technical_diff": {
                            "sha256_changed": previous.sha256 != upload.sha256
                            if previous
                            else True,
                            "mime_changed": (
                                previous.detected_mime_type != upload.detected_mime_type
                                if previous
                                else True
                            ),
                            "size_delta": upload.technical_metadata["file_size"]
                            - (previous.size_bytes if previous else 0),
                        },
                    },
                )
                result = MediaUploadResult(
                    asset.id, version.id, media_file.id, duplicate, upload.quarantined, False
                )
                record_idempotency(
                    self.session,
                    tenant_id=tenant_id,
                    scope="CREATE_MEDIA_VERSION",
                    key=idempotency_key,
                    request_hash=request_hash,
                    response_status=201,
                    response_body=result.as_dict(),
                )
            return result
        except Exception:
            if uploaded is not None:
                await self.storage.remove(bucket=uploaded[0], object_key=uploaded[1])
            raise

    async def list_assets(
        self,
        *,
        actor: Actor,
        query: str | None,
        status: MediaStatus | None,
        media_type: str | None,
        category_id: UUID | None,
        page: int,
        page_size: int,
    ) -> dict[str, Any]:
        tenant_id = self._tenant(actor)
        filters: list[Any] = [MediaAsset.tenant_id == tenant_id]
        if query:
            needle = query.strip()
            filters.append(
                or_(
                    MediaAsset.title.contains(needle, autoescape=True),
                    MediaAsset.description.contains(needle, autoescape=True),
                    cast(MediaAsset.id, String).contains(needle, autoescape=True),
                    MediaVersion.original_filename.contains(needle, autoescape=True),
                    MediaVersion.sha256.contains(needle, autoescape=True),
                )
            )
        if status is not None:
            filters.append(MediaAsset.status == status)
        if media_type:
            filters.append(MediaAsset.media_type == media_type)
        if category_id:
            filters.append(MediaAsset.category_id == category_id)
        base = (
            select(MediaAsset)
            .outerjoin(
                MediaVersion,
                (MediaVersion.media_asset_id == MediaAsset.id) & MediaVersion.is_current.is_(True),
            )
            .where(*filters)
        )
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        items = list(
            (
                await self.session.scalars(
                    base.order_by(MediaAsset.updated_at.desc(), MediaAsset.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).unique()
        )
        return {
            "items": [self._asset_summary(item) for item in items],
            "page": page,
            "page_size": page_size,
            "total": int(total or 0),
        }

    async def detail(self, *, actor: Actor, asset_id: UUID) -> dict[str, Any]:
        tenant_id = self._tenant(actor)
        asset = await self._asset(tenant_id, asset_id)
        versions = list(
            await self.session.scalars(
                select(MediaVersion)
                .where(MediaVersion.media_asset_id == asset.id)
                .order_by(MediaVersion.version_number.desc())
            )
        )
        version_ids = [item.id for item in versions]
        metadata = (
            list(
                await self.session.scalars(
                    select(MediaMetadata).where(MediaMetadata.media_version_id.in_(version_ids))
                )
            )
            if version_ids
            else []
        )
        variants = (
            list(
                await self.session.scalars(
                    select(MediaVariant).where(MediaVariant.source_version_id.in_(version_ids))
                )
            )
            if version_ids
            else []
        )
        relations = list(
            await self.session.scalars(
                select(MediaRelation).where(
                    MediaRelation.tenant_id == tenant_id,
                    or_(
                        MediaRelation.source_asset_id == asset.id,
                        MediaRelation.target_asset_id == asset.id,
                    ),
                )
            )
        )
        rights = await self.session.scalar(
            select(MediaRights).where(MediaRights.media_asset_id == asset.id)
        )
        approvals = list(
            await self.session.scalars(
                select(MediaApproval)
                .where(MediaApproval.media_asset_id == asset.id)
                .order_by(MediaApproval.created_at.desc())
            )
        )
        tags = list(
            await self.session.scalars(
                select(MediaTag)
                .join(MediaAssetTag, MediaAssetTag.tag_id == MediaTag.id)
                .where(MediaAssetTag.media_asset_id == asset.id)
                .order_by(MediaTag.name)
            )
        )
        audit = list(
            await self.session.scalars(
                select(AuditEvent)
                .where(AuditEvent.media_asset_id == asset.id)
                .order_by(AuditEvent.created_at.desc())
            )
        )
        metadata_by_version = {item.media_version_id: item for item in metadata}
        return {
            **self._asset_summary(asset),
            "description": asset.description,
            "revision": asset.revision,
            "assigned_to": str(asset.assigned_to) if asset.assigned_to else None,
            "retention_status": asset.retention_status.value,
            "confidentiality": asset.confidentiality.value,
            "deletion_locked": asset.deletion_locked,
            "tags": [{"id": str(tag.id), "name": tag.name} for tag in tags],
            "versions": [
                {
                    "id": str(version.id),
                    "version_number": version.version_number,
                    "file_id": str(version.media_file_id),
                    "original_filename": version.original_filename,
                    "mime_type": version.detected_mime_type,
                    "size_bytes": version.size_bytes,
                    "sha256": version.sha256,
                    "change_reason": version.change_reason,
                    "approval_status": version.approval_status.value,
                    "is_current": version.is_current,
                    "created_at": version.created_at.isoformat(),
                    "technical_metadata": (
                        metadata_by_version[version.id].technical
                        if version.id in metadata_by_version
                        else {}
                    ),
                    "business_metadata": (
                        metadata_by_version[version.id].business
                        if version.id in metadata_by_version
                        else {}
                    ),
                }
                for version in versions
            ],
            "variants": [self._variant_dict(item) for item in variants],
            "relations": [self._relation_dict(item) for item in relations],
            "rights": self._rights_dict(rights) if rights else None,
            "approvals": [self._approval_dict(item) for item in approvals],
            "audit": [
                {
                    "id": str(item.id),
                    "event_type": item.event_type,
                    "payload": item.payload,
                    "created_at": item.created_at.isoformat(),
                }
                for item in audit
            ],
        }

    async def update_asset(
        self,
        *,
        actor: Actor,
        asset_id: UUID,
        expected_revision: int,
        title: str,
        description: str | None,
        category_id: UUID | None,
        tag_ids: list[UUID],
        business_metadata: dict[str, Any],
        custom_metadata: dict[str, Any],
    ) -> MediaAsset:
        tenant_id = self._tenant(actor)
        async with self.session.begin():
            asset = await self._asset(tenant_id, asset_id, locked=True)
            self._expect_revision(asset, expected_revision)
            if category_id is not None and not await self.session.scalar(
                select(MediaCategory.id).where(
                    MediaCategory.id == category_id, MediaCategory.tenant_id == tenant_id
                )
            ):
                raise MediaNotFoundError("Media category was not found")
            if tag_ids:
                found = set(
                    await self.session.scalars(
                        select(MediaTag.id).where(
                            MediaTag.id.in_(tag_ids), MediaTag.tenant_id == tenant_id
                        )
                    )
                )
                if found != set(tag_ids):
                    raise MediaNotFoundError("One or more media tags were not found")
            asset.title = title.strip()
            asset.description = (description or "").strip() or None
            asset.category_id = category_id
            asset.revision += 1
            await self.session.execute(
                delete(MediaAssetTag).where(MediaAssetTag.media_asset_id == asset.id)
            )
            self.session.add_all(
                [MediaAssetTag(media_asset_id=asset.id, tag_id=tag_id) for tag_id in tag_ids]
            )
            current_version = await self._current_version(asset.id)
            metadata = await self.session.scalar(
                select(MediaMetadata).where(MediaMetadata.media_version_id == current_version.id)
            )
            if metadata is not None:
                metadata.business = business_metadata
                metadata.custom = custom_metadata
            self._audit(actor, asset, "MEDIA_METADATA_UPDATED", {"revision": asset.revision})
        return asset

    async def create_category(
        self, *, actor: Actor, name: str, slug: str, parent_id: UUID | None
    ) -> MediaCategory:
        tenant_id = self._tenant(actor)
        async with self.session.begin():
            if parent_id is not None and not await self.session.scalar(
                select(MediaCategory.id).where(
                    MediaCategory.id == parent_id, MediaCategory.tenant_id == tenant_id
                )
            ):
                raise MediaNotFoundError("Parent category was not found")
            category = MediaCategory(
                tenant_id=tenant_id,
                name=name.strip(),
                slug=slug.strip().lower(),
                parent_id=parent_id,
            )
            self.session.add(category)
            self._audit(actor, None, "MEDIA_CATEGORY_CREATED", {"name": category.name})
        return category

    async def create_tag(self, *, actor: Actor, name: str, synonyms: list[str]) -> MediaTag:
        tenant_id = self._tenant(actor)
        async with self.session.begin():
            tag = MediaTag(
                tenant_id=tenant_id,
                name=name.strip(),
                synonyms=sorted({item.strip() for item in synonyms if item.strip()}),
            )
            self.session.add(tag)
            self._audit(actor, None, "MEDIA_TAG_CREATED", {"name": tag.name})
        return tag

    async def taxonomy(self, *, actor: Actor) -> dict[str, Any]:
        tenant_id = self._tenant(actor)
        categories = list(
            await self.session.scalars(
                select(MediaCategory)
                .where(MediaCategory.tenant_id == tenant_id, MediaCategory.active.is_(True))
                .order_by(MediaCategory.name)
            )
        )
        tags = list(
            await self.session.scalars(
                select(MediaTag)
                .where(MediaTag.tenant_id == tenant_id, MediaTag.active.is_(True))
                .order_by(MediaTag.name)
            )
        )
        return {
            "categories": [
                {
                    "id": str(item.id),
                    "parent_id": str(item.parent_id) if item.parent_id else None,
                    "name": item.name,
                    "slug": item.slug,
                }
                for item in categories
            ],
            "tags": [
                {"id": str(item.id), "name": item.name, "synonyms": item.synonyms} for item in tags
            ],
        }

    async def add_relation(
        self,
        *,
        actor: Actor,
        source_id: UUID,
        target_id: UUID,
        relation_type: MediaRelationType,
    ) -> MediaRelation:
        tenant_id = self._tenant(actor)
        if source_id == target_id:
            raise MediaConflictError("A media asset cannot relate to itself")
        async with self.session.begin():
            source = await self._asset(tenant_id, source_id)
            await self._asset(tenant_id, target_id)
            if await self._would_cycle(tenant_id, source_id, target_id):
                raise MediaConflictError("Media relation would create a cycle")
            relation = MediaRelation(
                tenant_id=tenant_id,
                source_asset_id=source_id,
                target_asset_id=target_id,
                relation_type=relation_type,
                created_by=actor.id,
            )
            self.session.add(relation)
            self._audit(
                actor,
                source,
                "MEDIA_RELATION_CREATED",
                {"target_id": str(target_id), "relation_type": relation_type.value},
            )
        return relation

    async def add_variant(
        self,
        *,
        actor: Actor,
        asset_id: UUID,
        version_id: UUID,
        variant_type: str,
        technical_properties: dict[str, Any],
    ) -> MediaVariant:
        tenant_id = self._tenant(actor)
        async with self.session.begin():
            asset = await self._asset(tenant_id, asset_id)
            version = await self.session.scalar(
                select(MediaVersion).where(
                    MediaVersion.id == version_id, MediaVersion.media_asset_id == asset.id
                )
            )
            if version is None:
                raise MediaNotFoundError("Media version was not found")
            variant = MediaVariant(
                source_version_id=version.id,
                variant_type=variant_type.strip().upper(),
                technical_properties=technical_properties,
                generation_status=MediaVariantStatus.REGISTERED,
                generation_source="MANUAL_REGISTRATION",
                verification_result={"external_processing": False},
            )
            self.session.add(variant)
            self._audit(
                actor,
                asset,
                "MEDIA_VARIANT_REGISTERED",
                {"variant_type": variant.variant_type, "version_id": str(version.id)},
            )
        return variant

    async def save_rights(
        self,
        *,
        actor: Actor,
        asset_id: UUID,
        expected_revision: int,
        values: dict[str, Any],
    ) -> MediaRights:
        tenant_id = self._tenant(actor)
        async with self.session.begin():
            asset = await self._asset(tenant_id, asset_id, locked=True)
            self._expect_revision(asset, expected_revision)
            proof_id = values.get("proof_media_asset_id")
            if proof_id is not None:
                await self._asset(tenant_id, proof_id)
            rights = await self.session.scalar(
                select(MediaRights).where(MediaRights.media_asset_id == asset.id)
            )
            if rights is None:
                rights = MediaRights(media_asset_id=asset.id, **values)
                self.session.add(rights)
            else:
                for key, value in values.items():
                    setattr(rights, key, value)
                rights.review_status = RightsReviewStatus.PENDING
                rights.reviewed_by = None
                rights.reviewed_at = None
                rights.review_reason = None
            asset.revision += 1
            asset.status = MediaStatus.RIGHTS_REVIEW
            self._audit(actor, asset, "MEDIA_RIGHTS_UPDATED", {"revision": asset.revision})
        return rights

    async def review_rights(
        self,
        *,
        actor: Actor,
        asset_id: UUID,
        approve: bool,
        reason: str,
    ) -> MediaRights:
        tenant_id = self._tenant(actor)
        async with self.session.begin():
            asset = await self._asset(tenant_id, asset_id, locked=True)
            rights = await self.session.scalar(
                select(MediaRights).where(MediaRights.media_asset_id == asset.id).with_for_update()
            )
            if rights is None:
                raise MediaRightsError("Rights information is missing")
            now = datetime.now(UTC)
            if approve and rights.usage_end is not None and rights.usage_end <= now:
                rights.review_status = RightsReviewStatus.EXPIRED
                raise MediaRightsError("Rights usage period has expired")
            rights.review_status = (
                RightsReviewStatus.APPROVED if approve else RightsReviewStatus.REJECTED
            )
            rights.reviewed_by = actor.id
            rights.review_reason = reason.strip()
            rights.reviewed_at = now
            asset.status = MediaStatus.CONTENT_REVIEW if approve else MediaStatus.CHANGES_REQUESTED
            asset.revision += 1
            self._audit(
                actor,
                asset,
                "MEDIA_RIGHTS_APPROVED" if approve else "MEDIA_RIGHTS_REJECTED",
                {"reason": reason.strip()},
            )
        return rights

    async def request_approval(self, *, actor: Actor, asset_id: UUID) -> MediaApproval:
        tenant_id = self._tenant(actor)
        async with self.session.begin():
            asset = await self._asset(tenant_id, asset_id, locked=True)
            rights = await self.session.scalar(
                select(MediaRights).where(MediaRights.media_asset_id == asset.id)
            )
            if rights is None or rights.review_status != RightsReviewStatus.APPROVED:
                raise MediaRightsError("Approved rights are required before content approval")
            version = await self._current_version(asset.id)
            if await self.session.scalar(
                select(MediaApproval.id).where(
                    MediaApproval.media_version_id == version.id,
                    MediaApproval.status == MediaApprovalStatus.PENDING,
                )
            ):
                raise MediaConflictError("Approval is already pending for this media version")
            approval = MediaApproval(
                tenant_id=tenant_id,
                media_asset_id=asset.id,
                media_version_id=version.id,
                requested_by=actor.id,
                status=MediaApprovalStatus.PENDING,
            )
            self.session.add(approval)
            version.approval_status = MediaApprovalStatus.PENDING
            asset.approval_status = MediaApprovalStatus.PENDING
            asset.status = MediaStatus.CONTENT_REVIEW
            asset.revision += 1
            self._audit(actor, asset, "MEDIA_APPROVAL_REQUESTED", {"version_id": str(version.id)})
        return approval

    async def resolve_approval(
        self,
        *,
        actor: Actor,
        asset_id: UUID,
        approval_id: UUID,
        approve: bool,
        reason: str,
    ) -> MediaApproval:
        tenant_id = self._tenant(actor)
        async with self.session.begin():
            asset = await self._asset(tenant_id, asset_id, locked=True)
            approval = await self.session.scalar(
                select(MediaApproval)
                .where(
                    MediaApproval.id == approval_id,
                    MediaApproval.media_asset_id == asset.id,
                    MediaApproval.status == MediaApprovalStatus.PENDING,
                )
                .with_for_update()
            )
            if approval is None:
                raise MediaNotFoundError("Pending media approval was not found")
            if approval.requested_by == actor.id:
                raise AuthorizationError("Self-approval of a media version is not allowed")
            version = await self.session.get(MediaVersion, approval.media_version_id)
            if version is None or not version.is_current:
                raise MediaConflictError("Approval is not bound to the current version")
            approval.status = (
                MediaApprovalStatus.APPROVED if approve else MediaApprovalStatus.REJECTED
            )
            approval.resolved_by = actor.id
            approval.reason = reason.strip()
            approval.resolved_at = datetime.now(UTC)
            version.approval_status = approval.status
            asset.approval_status = approval.status
            asset.status = MediaStatus.READY if approve else MediaStatus.CHANGES_REQUESTED
            asset.revision += 1
            self._audit(
                actor,
                asset,
                "MEDIA_APPROVED" if approve else "MEDIA_REJECTED",
                {"approval_id": str(approval.id), "reason": reason.strip()},
            )
        return approval

    async def archive(self, *, actor: Actor, asset_id: UUID, expected_revision: int) -> MediaAsset:
        tenant_id = self._tenant(actor)
        async with self.session.begin():
            asset = await self._asset(tenant_id, asset_id, locked=True)
            self._expect_revision(asset, expected_revision)
            asset.archived = True
            asset.status = MediaStatus.ARCHIVED
            asset.retention_status = RetentionStatus.ARCHIVED
            asset.revision += 1
            self._audit(actor, asset, "MEDIA_ARCHIVED", {"revision": asset.revision})
        return asset

    async def request_deletion(
        self, *, actor: Actor, asset_id: UUID, expected_revision: int, reason: str
    ) -> MediaDeletionRequest:
        tenant_id = self._tenant(actor)
        async with self.session.begin():
            asset = await self._asset(tenant_id, asset_id, locked=True)
            self._expect_revision(asset, expected_revision)
            if asset.deletion_locked or asset.retention_status == RetentionStatus.RETENTION_HOLD:
                raise MediaDeletionError("Media asset is protected by a deletion or retention hold")
            request = MediaDeletionRequest(
                tenant_id=tenant_id,
                media_asset_id=asset.id,
                requested_by=actor.id,
                reason=reason.strip(),
                status="REQUESTED",
            )
            self.session.add(request)
            asset.retention_status = RetentionStatus.DELETION_REQUESTED
            asset.status = MediaStatus.DELETION_PENDING
            asset.revision += 1
            self._audit(actor, asset, "MEDIA_DELETION_REQUESTED", {"reason": reason.strip()})
        return request

    async def approve_deletion(
        self, *, actor: Actor, asset_id: UUID, request_id: UUID, reason: str
    ) -> MediaDeletionRequest:
        tenant_id = self._tenant(actor)
        async with self.session.begin():
            asset = await self._asset(tenant_id, asset_id, locked=True)
            request = await self.session.scalar(
                select(MediaDeletionRequest)
                .where(
                    MediaDeletionRequest.id == request_id,
                    MediaDeletionRequest.media_asset_id == asset.id,
                    MediaDeletionRequest.status == "REQUESTED",
                )
                .with_for_update()
            )
            if request is None:
                raise MediaNotFoundError("Deletion request was not found")
            if request.requested_by == actor.id:
                raise AuthorizationError("Deletion request requires an independent approval")
            if asset.deletion_locked or asset.retention_status == RetentionStatus.RETENTION_HOLD:
                raise MediaDeletionError("Media asset is protected from deletion")
            relations = await self.session.scalar(
                select(func.count(MediaRelation.id)).where(
                    or_(
                        MediaRelation.source_asset_id == asset.id,
                        MediaRelation.target_asset_id == asset.id,
                    )
                )
            )
            if relations:
                raise MediaDeletionError("Media asset has active relationships")
            request.status = "APPROVED"
            request.approved_by = actor.id
            request.approved_at = datetime.now(UTC)
            request.reason = f"{request.reason}\nApproval: {reason.strip()}"
            asset.retention_status = RetentionStatus.DELETION_APPROVED
            self._queue(asset, None, "PURGE_MEDIA")
            self._audit(actor, asset, "MEDIA_DELETION_APPROVED", {"request_id": str(request.id)})
        return request

    async def create_collection(
        self,
        *,
        actor: Actor,
        name: str,
        description: str | None,
        visibility: MediaCollectionVisibility,
    ) -> MediaCollection:
        tenant_id = self._tenant(actor)
        async with self.session.begin():
            collection = MediaCollection(
                tenant_id=tenant_id,
                name=name.strip(),
                description=(description or "").strip() or None,
                owner_id=actor.id,
                visibility=visibility,
                status=MediaCollectionStatus.ACTIVE,
            )
            self.session.add(collection)
            await self.session.flush()
            self._collection_history(collection, actor, "CREATED", [])
            self._audit(
                actor, None, "MEDIA_COLLECTION_CREATED", {"collection_id": str(collection.id)}
            )
        return collection

    async def add_collection_item(
        self, *, actor: Actor, collection_id: UUID, asset_id: UUID
    ) -> MediaCollectionItem:
        tenant_id = self._tenant(actor)
        async with self.session.begin():
            collection = await self._collection(tenant_id, collection_id, locked=True)
            await self._asset(tenant_id, asset_id)
            position = (
                int(
                    await self.session.scalar(
                        select(func.coalesce(func.max(MediaCollectionItem.position), 0)).where(
                            MediaCollectionItem.collection_id == collection.id
                        )
                    )
                    or 0
                )
                + 1
            )
            item = MediaCollectionItem(
                collection_id=collection.id,
                media_asset_id=asset_id,
                position=position,
                added_by=actor.id,
            )
            self.session.add(item)
            await self.session.flush()
            self._collection_history(
                collection, actor, "ITEM_ADDED", await self._collection_ids(collection.id)
            )
            self._audit(
                actor,
                None,
                "MEDIA_COLLECTION_ITEM_ADDED",
                {"collection_id": str(collection.id), "asset_id": str(asset_id)},
            )
        return item

    async def reorder_collection(
        self, *, actor: Actor, collection_id: UUID, asset_ids: list[UUID]
    ) -> MediaCollection:
        tenant_id = self._tenant(actor)
        async with self.session.begin():
            collection = await self._collection(tenant_id, collection_id, locked=True)
            items = list(
                await self.session.scalars(
                    select(MediaCollectionItem)
                    .where(MediaCollectionItem.collection_id == collection.id)
                    .with_for_update()
                )
            )
            if {item.media_asset_id for item in items} != set(asset_ids) or len(items) != len(
                asset_ids
            ):
                raise MediaConflictError("Collection order must include every item exactly once")
            await self.session.execute(
                update(MediaCollectionItem)
                .where(MediaCollectionItem.collection_id == collection.id)
                .values(position=MediaCollectionItem.position + 1000000)
            )
            by_asset = {item.media_asset_id: item for item in items}
            for position, asset_id in enumerate(asset_ids, start=1):
                by_asset[asset_id].position = position
            self._collection_history(collection, actor, "REORDERED", asset_ids)
            self._audit(
                actor, None, "MEDIA_COLLECTION_REORDERED", {"collection_id": str(collection.id)}
            )
        return collection

    async def list_collections(self, *, actor: Actor) -> list[dict[str, Any]]:
        tenant_id = self._tenant(actor)
        collections = list(
            await self.session.scalars(
                select(MediaCollection)
                .where(MediaCollection.tenant_id == tenant_id)
                .order_by(MediaCollection.updated_at.desc())
            )
        )
        result: list[dict[str, Any]] = []
        for collection in collections:
            items = list(
                await self.session.scalars(
                    select(MediaCollectionItem)
                    .where(MediaCollectionItem.collection_id == collection.id)
                    .order_by(MediaCollectionItem.position)
                )
            )
            result.append(
                {
                    "id": str(collection.id),
                    "name": collection.name,
                    "description": collection.description,
                    "visibility": collection.visibility.value,
                    "status": collection.status.value,
                    "items": [
                        {"asset_id": str(item.media_asset_id), "position": item.position}
                        for item in items
                    ],
                }
            )
        return result

    async def file_for_download(
        self, *, actor: Actor, asset_id: UUID, version_id: UUID | None
    ) -> tuple[MediaAsset, MediaVersion, MediaFile]:
        tenant_id = self._tenant(actor)
        asset = await self._asset(tenant_id, asset_id)
        version = (
            await self.session.get(MediaVersion, version_id)
            if version_id
            else await self._current_version(asset.id)
        )
        if version is None or version.media_asset_id != asset.id:
            raise MediaNotFoundError("Media version was not found")
        media_file = await self.session.get(MediaFile, version.media_file_id)
        if media_file is None or media_file.tenant_id != tenant_id:
            raise MediaNotFoundError("Media file was not found")
        return asset, version, media_file

    async def audit_download(
        self, *, actor: Actor, asset: MediaAsset, version: MediaVersion, original: bool
    ) -> None:
        self._audit(
            actor,
            asset,
            "MEDIA_ORIGINAL_DOWNLOADED" if original else "MEDIA_PREVIEW_ACCESSED",
            {"version_id": str(version.id)},
        )
        await self.session.commit()

    async def _store_file(self, actor: Actor, upload: ValidatedMedia) -> tuple[MediaFile, bool]:
        tenant_id = self._tenant(actor)
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"media-file:{tenant_id}:{upload.sha256}:{len(upload.content)}"},
        )
        existing = await self.session.scalar(
            select(MediaFile).where(
                MediaFile.tenant_id == tenant_id,
                MediaFile.sha256 == upload.sha256,
                MediaFile.size_bytes == len(upload.content),
            )
        )
        if existing is not None:
            return existing, True
        bucket = get_settings().mediaos_private_bucket
        object_key = f"{tenant_id}/media/{upload.sha256[:2]}/{upload.sha256}"
        await self.storage.put_private(
            bucket=bucket,
            object_key=object_key,
            content=upload.content,
            content_type=upload.detected_mime_type,
        )
        media_file = MediaFile(
            tenant_id=tenant_id,
            created_by=actor.id,
            bucket=bucket,
            object_key=object_key,
            size_bytes=len(upload.content),
            sha256=upload.sha256,
            detected_mime_type=upload.detected_mime_type,
            file_signature=upload.file_signature,
            verification_status=(
                MediaVerificationStatus.PENDING
                if upload.quarantined
                else MediaVerificationStatus.VERIFIED
            ),
            storage_status=MediaStorageStatus.STORED,
            quarantined=upload.quarantined,
        )
        self.session.add(media_file)
        try:
            await self.session.flush()
        except Exception:
            await self.storage.remove(bucket=bucket, object_key=object_key)
            raise
        return media_file, False

    @staticmethod
    def _new_version(
        *,
        actor: Actor,
        asset: MediaAsset,
        media_file: MediaFile,
        upload: ValidatedMedia,
        original_filename: str | None,
        change_reason: str,
        version_number: int,
    ) -> MediaVersion:
        safe_name = PurePath(original_filename or f"media-{version_number}").name[:255]
        return MediaVersion(
            media_asset_id=asset.id,
            version_number=version_number,
            media_file_id=media_file.id,
            filename=safe_name or f"media-{version_number}",
            original_filename=safe_name or f"media-{version_number}",
            claimed_mime_type=upload.claimed_mime_type,
            detected_mime_type=upload.detected_mime_type,
            detected_media_type=upload.media_type,
            size_bytes=len(upload.content),
            sha256=upload.sha256,
            created_by=actor.id,
            change_reason=change_reason,
            technical_results={
                "signature": upload.file_signature,
                "validation_issues": list(upload.validation_issues),
            },
            approval_status=MediaApprovalStatus.NOT_REQUESTED,
            is_current=True,
        )

    async def _asset(self, tenant_id: UUID, asset_id: UUID, *, locked: bool = False) -> MediaAsset:
        statement = select(MediaAsset).where(
            MediaAsset.id == asset_id, MediaAsset.tenant_id == tenant_id
        )
        if locked:
            statement = statement.with_for_update()
        asset = await self.session.scalar(statement)
        if asset is None:
            raise MediaNotFoundError("Media asset was not found in the authenticated tenant")
        return asset

    async def _current_version(self, asset_id: UUID) -> MediaVersion:
        version = await self.session.scalar(
            select(MediaVersion).where(
                MediaVersion.media_asset_id == asset_id, MediaVersion.is_current.is_(True)
            )
        )
        if version is None:
            raise MediaNotFoundError("Current media version was not found")
        return version

    async def _collection(
        self, tenant_id: UUID, collection_id: UUID, *, locked: bool = False
    ) -> MediaCollection:
        statement = select(MediaCollection).where(
            MediaCollection.id == collection_id, MediaCollection.tenant_id == tenant_id
        )
        if locked:
            statement = statement.with_for_update()
        collection = await self.session.scalar(statement)
        if collection is None:
            raise MediaNotFoundError("Media collection was not found")
        return collection

    async def _would_cycle(self, tenant_id: UUID, source_id: UUID, target_id: UUID) -> bool:
        frontier = {target_id}
        visited: set[UUID] = set()
        while frontier:
            if source_id in frontier:
                return True
            visited.update(frontier)
            targets = set(
                await self.session.scalars(
                    select(MediaRelation.target_asset_id).where(
                        MediaRelation.tenant_id == tenant_id,
                        MediaRelation.source_asset_id.in_(frontier),
                    )
                )
            )
            frontier = targets - visited
        return False

    def _queue(self, asset: MediaAsset, version: MediaVersion | None, task_type: str) -> None:
        self.session.add(
            MediaTask(
                tenant_id=asset.tenant_id,
                media_asset_id=asset.id,
                media_version_id=version.id if version else None,
                task_type=task_type,
                status=TaskStatus.PENDING,
                payload={"external_effect": False},
            )
        )

    def _audit(
        self,
        actor: Actor,
        asset: MediaAsset | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        tenant_id = self._tenant(actor)
        self.session.add(
            AuditEvent(
                tenant_id=tenant_id,
                job_id=None,
                media_asset_id=asset.id if asset else None,
                actor_id=actor.id,
                actor_type=actor.type,
                event_type=event_type,
                payload=payload,
            )
        )

    def _collection_history(
        self, collection: MediaCollection, actor: Actor, change_type: str, asset_ids: list[UUID]
    ) -> None:
        self.session.add(
            MediaCollectionHistory(
                collection_id=collection.id,
                actor_id=actor.id,
                change_type=change_type,
                snapshot={"asset_ids": [str(item) for item in asset_ids]},
            )
        )

    async def _collection_ids(self, collection_id: UUID) -> list[UUID]:
        return list(
            await self.session.scalars(
                select(MediaCollectionItem.media_asset_id)
                .where(MediaCollectionItem.collection_id == collection_id)
                .order_by(MediaCollectionItem.position)
            )
        )

    @staticmethod
    def _tenant(actor: Actor) -> UUID:
        if actor.tenant_id is None:
            raise TenantBoundaryError("Authenticated actor has no tenant")
        return actor.tenant_id

    @staticmethod
    def _expect_revision(asset: MediaAsset, expected_revision: int) -> None:
        if asset.revision != expected_revision:
            raise VersionConflictError(
                "Media asset revision does not match",
                details={"expected": expected_revision, "current": asset.revision},
            )

    @staticmethod
    def _upload_result(body: dict[str, Any], *, replayed: bool) -> MediaUploadResult:
        return MediaUploadResult(
            asset_id=UUID(body["asset_id"]),
            version_id=UUID(body["version_id"]),
            file_id=UUID(body["file_id"]),
            duplicate_binary=bool(body["duplicate_binary"]),
            quarantined=bool(body["quarantined"]),
            replayed=replayed,
        )

    @staticmethod
    def _asset_summary(asset: MediaAsset) -> dict[str, Any]:
        return {
            "id": str(asset.id),
            "tenant_id": str(asset.tenant_id),
            "title": asset.title,
            "media_type": asset.media_type.value,
            "status": asset.status.value,
            "technical_status": asset.technical_status.value,
            "approval_status": asset.approval_status.value,
            "storage_status": asset.storage_status.value,
            "current_version_number": asset.current_version_number,
            "category_id": str(asset.category_id) if asset.category_id else None,
            "archived": asset.archived,
            "created_by": str(asset.created_by),
            "created_at": asset.created_at.isoformat(),
            "updated_at": asset.updated_at.isoformat(),
        }

    @staticmethod
    def _variant_dict(item: MediaVariant) -> dict[str, Any]:
        return {
            "id": str(item.id),
            "source_version_id": str(item.source_version_id),
            "variant_type": item.variant_type,
            "technical_properties": item.technical_properties,
            "generation_status": item.generation_status.value,
            "generation_source": item.generation_source,
        }

    @staticmethod
    def _relation_dict(item: MediaRelation) -> dict[str, Any]:
        return {
            "id": str(item.id),
            "source_asset_id": str(item.source_asset_id),
            "target_asset_id": str(item.target_asset_id),
            "relation_type": item.relation_type.value,
        }

    @staticmethod
    def _rights_dict(item: MediaRights) -> dict[str, Any]:
        return {
            "id": str(item.id),
            "rights_holder": item.rights_holder,
            "license_type": item.license_type,
            "usage_start": item.usage_start.isoformat() if item.usage_start else None,
            "usage_end": item.usage_end.isoformat() if item.usage_end else None,
            "allowed_uses": item.allowed_uses,
            "allowed_regions": item.allowed_regions,
            "allowed_channels": item.allowed_channels,
            "attribution_required": item.attribution_required,
            "editing_allowed": item.editing_allowed,
            "redistribution_allowed": item.redistribution_allowed,
            "restrictions": item.restrictions,
            "proof_media_asset_id": str(item.proof_media_asset_id)
            if item.proof_media_asset_id
            else None,
            "review_status": item.review_status.value,
            "review_reason": item.review_reason,
        }

    @staticmethod
    def _approval_dict(item: MediaApproval) -> dict[str, Any]:
        return {
            "id": str(item.id),
            "media_version_id": str(item.media_version_id),
            "requested_by": str(item.requested_by),
            "resolved_by": str(item.resolved_by) if item.resolved_by else None,
            "status": item.status.value,
            "reason": item.reason,
            "created_at": item.created_at.isoformat(),
        }
