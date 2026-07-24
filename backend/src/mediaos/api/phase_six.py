"""Hauptblock 6: authenticated, tenant-scoped media library API."""

from datetime import datetime
from typing import Annotated, Any
from urllib.parse import quote
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.api.auth import (
    SessionContext,
    require_admin_actor,
    require_approval_actor,
    require_session_context,
    require_write_actor,
)
from mediaos.application.media_service import MediaService
from mediaos.application.media_validation import validate_media
from mediaos.config import get_settings
from mediaos.database import get_session
from mediaos.domain.actor import Actor
from mediaos.domain.enums import (
    MediaApprovalStatus,
    MediaCollectionStatus,
    MediaCollectionVisibility,
    MediaRelationType,
    MediaStatus,
    RightsReviewStatus,
    RoleName,
)
from mediaos.infrastructure.object_storage import ObjectStorage

router = APIRouter(prefix="/api/v1", tags=["block-six-media"])
Session = Annotated[AsyncSession, Depends(get_session)]


class MediaUpdateBody(BaseModel):
    expected_revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    category_id: UUID | None = None
    tag_ids: list[UUID] = Field(default_factory=list, max_length=100)
    business_metadata: dict[str, Any] = Field(default_factory=dict)
    custom_metadata: dict[str, Any] = Field(default_factory=dict)


class CategoryBody(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    slug: str = Field(min_length=1, max_length=150, pattern=r"^[a-z0-9][a-z0-9-]*$")
    parent_id: UUID | None = None


class TagBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    synonyms: list[str] = Field(default_factory=list, max_length=50)


class ActiveBody(BaseModel):
    active: bool


class RelationBody(BaseModel):
    target_asset_id: UUID
    relation_type: MediaRelationType


class VariantBody(BaseModel):
    version_id: UUID
    variant_type: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    technical_properties: dict[str, Any] = Field(default_factory=dict)


class RightsBody(BaseModel):
    expected_revision: int = Field(ge=1)
    rights_holder: str = Field(min_length=1, max_length=300)
    license_type: str = Field(min_length=1, max_length=150)
    usage_start: datetime | None = None
    usage_end: datetime | None = None
    allowed_uses: list[str] = Field(default_factory=list, max_length=100)
    allowed_regions: list[str] = Field(default_factory=list, max_length=100)
    allowed_channels: list[str] = Field(default_factory=list, max_length=100)
    attribution_required: bool = False
    editing_allowed: bool = False
    redistribution_allowed: bool = False
    restrictions: str | None = Field(default=None, max_length=5000)
    proof_media_asset_id: UUID | None = None


class ReviewBody(BaseModel):
    approve: bool
    reason: str = Field(min_length=1, max_length=2000)


class ExpectedRevisionBody(BaseModel):
    expected_revision: int = Field(ge=1)


class DeletionBody(ExpectedRevisionBody):
    reason: str = Field(min_length=1, max_length=2000)


class DeletionApprovalBody(BaseModel):
    request_id: UUID
    reason: str = Field(min_length=1, max_length=2000)


class CollectionBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    visibility: MediaCollectionVisibility = MediaCollectionVisibility.TENANT


class CollectionUpdateBody(CollectionBody):
    status: MediaCollectionStatus = MediaCollectionStatus.ACTIVE


class CollectionItemBody(BaseModel):
    asset_id: UUID


class CollectionOrderBody(BaseModel):
    asset_ids: list[UUID] = Field(min_length=1, max_length=500)


@router.get("/media-assets")
async def list_media_assets(
    session: Session,
    context: Annotated[SessionContext, Depends(require_session_context)],
    query: Annotated[str | None, Query(max_length=300)] = None,
    media_status: MediaStatus | None = None,
    media_type: Annotated[str | None, Query(max_length=30)] = None,
    category_id: UUID | None = None,
    tag_id: UUID | None = None,
    rights_status: RightsReviewStatus | None = None,
    approval_status: MediaApprovalStatus | None = None,
    archived: bool | None = None,
    created_by: UUID | None = None,
    assigned_to: UUID | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    rights_expiring_before: datetime | None = None,
    sort: Annotated[
        str,
        Query(pattern=r"^(updated_desc|updated_asc|created_desc|title_asc)$"),
    ] = "updated_desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 24,
) -> dict[str, Any]:
    return await MediaService(session).list_assets(
        actor=context.actor,
        query=query,
        status=media_status,
        media_type=media_type,
        category_id=category_id,
        tag_id=tag_id,
        rights_status=rights_status,
        approval_status=approval_status,
        archived=archived,
        created_by=created_by,
        assigned_to=assigned_to,
        created_from=created_from,
        created_to=created_to,
        rights_expiring_before=rights_expiring_before,
        sort=sort,
        page=page,
        page_size=page_size,
    )


@router.post("/media-assets", status_code=status.HTTP_201_CREATED)
async def create_media_asset(
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    title: Annotated[str, Form(min_length=1, max_length=300)],
    upload: Annotated[UploadFile, File()],
    description: Annotated[str | None, Form(max_length=5000)] = None,
) -> dict[str, Any]:
    settings = get_settings()
    content = await upload.read(settings.mediaos_media_upload_max_bytes + 1)
    validated = validate_media(
        content,
        claimed_mime_type=upload.content_type,
        original_filename=upload.filename,
        max_bytes=settings.mediaos_media_upload_max_bytes,
    )
    result = await MediaService(session).create_asset(
        actor=actor,
        idempotency_key=idempotency_key,
        title=title,
        description=description,
        upload=validated,
        original_filename=upload.filename,
    )
    return result.as_dict()


@router.get("/media-assets/{asset_id}")
async def media_asset_detail(
    asset_id: UUID,
    session: Session,
    context: Annotated[SessionContext, Depends(require_session_context)],
) -> dict[str, Any]:
    return await MediaService(session).detail(actor=context.actor, asset_id=asset_id)


@router.post("/media-assets/{asset_id}/versions", status_code=status.HTTP_201_CREATED)
async def create_media_version(
    asset_id: UUID,
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    expected_revision: Annotated[int, Form(ge=1)],
    reason: Annotated[str, Form(min_length=1, max_length=2000)],
    upload: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    settings = get_settings()
    content = await upload.read(settings.mediaos_media_upload_max_bytes + 1)
    validated = validate_media(
        content,
        claimed_mime_type=upload.content_type,
        original_filename=upload.filename,
        max_bytes=settings.mediaos_media_upload_max_bytes,
    )
    result = await MediaService(session).add_version(
        actor=actor,
        asset_id=asset_id,
        expected_revision=expected_revision,
        idempotency_key=idempotency_key,
        reason=reason,
        upload=validated,
        original_filename=upload.filename,
    )
    return result.as_dict()


@router.patch("/media-assets/{asset_id}")
async def update_media_asset(
    asset_id: UUID,
    body: MediaUpdateBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
) -> dict[str, Any]:
    asset = await MediaService(session).update_asset(
        actor=actor, asset_id=asset_id, **body.model_dump()
    )
    return {"id": str(asset.id), "revision": asset.revision, "status": asset.status.value}


@router.get("/media-taxonomy")
async def media_taxonomy(
    session: Session,
    context: Annotated[SessionContext, Depends(require_session_context)],
) -> dict[str, Any]:
    return await MediaService(session).taxonomy(actor=context.actor)


@router.post("/media-categories")
async def create_media_category(
    body: CategoryBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_admin_actor)],
) -> dict[str, Any]:
    item = await MediaService(session).create_category(actor=actor, **body.model_dump())
    return {"id": str(item.id), "name": item.name, "slug": item.slug}


@router.post("/media-tags")
async def create_media_tag(
    body: TagBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
) -> dict[str, Any]:
    item = await MediaService(session).create_tag(actor=actor, **body.model_dump())
    return {"id": str(item.id), "name": item.name, "synonyms": item.synonyms}


@router.patch("/media-categories/{category_id}")
async def set_media_category_active(
    category_id: UUID,
    body: ActiveBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_admin_actor)],
) -> dict[str, Any]:
    item = await MediaService(session).set_category_active(
        actor=actor, category_id=category_id, active=body.active
    )
    return {"id": str(item.id), "active": item.active}


@router.patch("/media-tags/{tag_id}")
async def set_media_tag_active(
    tag_id: UUID,
    body: ActiveBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_admin_actor)],
) -> dict[str, Any]:
    item = await MediaService(session).set_tag_active(
        actor=actor, tag_id=tag_id, active=body.active
    )
    return {"id": str(item.id), "active": item.active}


@router.post("/media-assets/{asset_id}/relations")
async def create_media_relation(
    asset_id: UUID,
    body: RelationBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
) -> dict[str, Any]:
    item = await MediaService(session).add_relation(
        actor=actor,
        source_id=asset_id,
        target_id=body.target_asset_id,
        relation_type=body.relation_type,
    )
    return {"id": str(item.id), "relation_type": item.relation_type.value}


@router.post("/media-assets/{asset_id}/variants")
async def create_media_variant(
    asset_id: UUID,
    body: VariantBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
) -> dict[str, Any]:
    item = await MediaService(session).add_variant(
        actor=actor, asset_id=asset_id, **body.model_dump()
    )
    return {"id": str(item.id), "variant_type": item.variant_type}


@router.put("/media-assets/{asset_id}/rights")
async def save_media_rights(
    asset_id: UUID,
    body: RightsBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
) -> dict[str, Any]:
    values = body.model_dump(exclude={"expected_revision"})
    item = await MediaService(session).save_rights(
        actor=actor,
        asset_id=asset_id,
        expected_revision=body.expected_revision,
        values=values,
    )
    return {"id": str(item.id), "review_status": item.review_status.value}


@router.post("/media-assets/{asset_id}/rights/review")
async def review_media_rights(
    asset_id: UUID,
    body: ReviewBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_approval_actor)],
) -> dict[str, Any]:
    item = await MediaService(session).review_rights(
        actor=actor, asset_id=asset_id, **body.model_dump()
    )
    return {"id": str(item.id), "review_status": item.review_status.value}


@router.post("/media-assets/{asset_id}/approvals")
async def request_media_approval(
    asset_id: UUID,
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
) -> dict[str, Any]:
    item = await MediaService(session).request_approval(actor=actor, asset_id=asset_id)
    return {"id": str(item.id), "status": item.status.value}


@router.post("/media-assets/{asset_id}/approvals/{approval_id}/resolve")
async def resolve_media_approval(
    asset_id: UUID,
    approval_id: UUID,
    body: ReviewBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_approval_actor)],
) -> dict[str, Any]:
    item = await MediaService(session).resolve_approval(
        actor=actor,
        asset_id=asset_id,
        approval_id=approval_id,
        **body.model_dump(),
    )
    return {"id": str(item.id), "status": item.status.value}


@router.post("/media-assets/{asset_id}/archive")
async def archive_media_asset(
    asset_id: UUID,
    body: ExpectedRevisionBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
) -> dict[str, Any]:
    item = await MediaService(session).archive(actor=actor, asset_id=asset_id, **body.model_dump())
    return {"id": str(item.id), "status": item.status.value, "revision": item.revision}


@router.post("/media-assets/{asset_id}/deletion-requests")
async def request_media_deletion(
    asset_id: UUID,
    body: DeletionBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
) -> dict[str, Any]:
    item = await MediaService(session).request_deletion(
        actor=actor, asset_id=asset_id, **body.model_dump()
    )
    return {"id": str(item.id), "status": item.status}


@router.post("/media-assets/{asset_id}/deletion-approvals")
async def approve_media_deletion(
    asset_id: UUID,
    body: DeletionApprovalBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_admin_actor)],
) -> dict[str, Any]:
    item = await MediaService(session).approve_deletion(
        actor=actor, asset_id=asset_id, **body.model_dump()
    )
    return {"id": str(item.id), "status": item.status}


@router.get("/media-assets/{asset_id}/preview")
async def preview_media_asset(
    asset_id: UUID,
    request: Request,
    session: Session,
    context: Annotated[SessionContext, Depends(require_session_context)],
    version_id: UUID | None = None,
) -> Response:
    return await _media_response(
        request=request,
        session=session,
        context=context,
        asset_id=asset_id,
        version_id=version_id,
        original=False,
    )


@router.get("/media-assets/{asset_id}/download")
async def download_media_asset(
    asset_id: UUID,
    request: Request,
    session: Session,
    context: Annotated[SessionContext, Depends(require_session_context)],
    version_id: UUID | None = None,
) -> Response:
    return await _media_response(
        request=request,
        session=session,
        context=context,
        asset_id=asset_id,
        version_id=version_id,
        original=True,
    )


@router.get("/media-collections")
async def media_collections(
    session: Session,
    context: Annotated[SessionContext, Depends(require_session_context)],
) -> dict[str, Any]:
    return {"items": await MediaService(session).list_collections(actor=context.actor)}


@router.post("/media-collections")
async def create_media_collection(
    body: CollectionBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
) -> dict[str, Any]:
    item = await MediaService(session).create_collection(actor=actor, **body.model_dump())
    return {"id": str(item.id), "name": item.name}


@router.patch("/media-collections/{collection_id}")
async def update_media_collection(
    collection_id: UUID,
    body: CollectionUpdateBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
) -> dict[str, Any]:
    item = await MediaService(session).update_collection(
        actor=actor, collection_id=collection_id, **body.model_dump()
    )
    return {"id": str(item.id), "name": item.name, "status": item.status.value}


@router.post("/media-collections/{collection_id}/items")
async def add_media_collection_item(
    collection_id: UUID,
    body: CollectionItemBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
) -> dict[str, Any]:
    item = await MediaService(session).add_collection_item(
        actor=actor, collection_id=collection_id, asset_id=body.asset_id
    )
    return {"id": str(item.id), "position": item.position}


@router.put("/media-collections/{collection_id}/order")
async def reorder_media_collection(
    collection_id: UUID,
    body: CollectionOrderBody,
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
) -> dict[str, Any]:
    item = await MediaService(session).reorder_collection(
        actor=actor, collection_id=collection_id, asset_ids=body.asset_ids
    )
    return {"id": str(item.id), "updated_at": item.updated_at.isoformat()}


@router.delete("/media-collections/{collection_id}/items/{asset_id}")
async def remove_media_collection_item(
    collection_id: UUID,
    asset_id: UUID,
    session: Session,
    actor: Annotated[Actor, Depends(require_write_actor)],
) -> dict[str, Any]:
    item = await MediaService(session).remove_collection_item(
        actor=actor, collection_id=collection_id, asset_id=asset_id
    )
    return {"id": str(item.id), "updated_at": item.updated_at.isoformat()}


async def _media_response(
    *,
    request: Request,
    session: AsyncSession,
    context: SessionContext,
    asset_id: UUID,
    version_id: UUID | None,
    original: bool,
) -> Response:
    service = MediaService(session)
    asset, version, media_file = await service.file_for_download(
        actor=context.actor, asset_id=asset_id, version_id=version_id
    )
    if RoleName.READER in context.actor.roles and asset.status != MediaStatus.READY:
        from mediaos.application.errors import AuthorizationError

        raise AuthorizationError("Readers may only access approved, ready media")
    content = await ObjectStorage().get_private(
        bucket=media_file.bucket, object_key=media_file.object_key
    )
    await service.audit_download(
        actor=context.actor, asset=asset, version=version, original=original
    )
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    }
    encoded_name = quote(version.original_filename, safe="")
    disposition = "attachment" if original else "inline"
    headers["Content-Disposition"] = f"{disposition}; filename*=UTF-8''{encoded_name}"
    range_header = request.headers.get("range")
    if range_header:
        start, end = _parse_range(range_header, len(content))
        headers["Content-Range"] = f"bytes {start}-{end}/{len(content)}"
        headers["Content-Length"] = str(end - start + 1)
        return Response(
            content=content[start : end + 1],
            status_code=206,
            media_type=media_file.detected_mime_type,
            headers=headers,
        )
    headers["Content-Length"] = str(len(content))
    return Response(content=content, media_type=media_file.detected_mime_type, headers=headers)


def _parse_range(value: str, size: int) -> tuple[int, int]:
    from fastapi import HTTPException

    if not value.startswith("bytes=") or "," in value:
        raise HTTPException(status_code=416, detail="Only one byte range is supported")
    raw_start, separator, raw_end = value.removeprefix("bytes=").partition("-")
    if separator != "-":
        raise HTTPException(status_code=416, detail="Invalid byte range")
    try:
        if raw_start:
            start = int(raw_start)
            end = int(raw_end) if raw_end else size - 1
        else:
            suffix = int(raw_end)
            start = max(size - suffix, 0)
            end = size - 1
    except ValueError as exc:
        raise HTTPException(status_code=416, detail="Invalid byte range") from exc
    if start < 0 or end < start or start >= size:
        raise HTTPException(status_code=416, detail="Unsatisfiable byte range")
    return start, min(end, size - 1)
