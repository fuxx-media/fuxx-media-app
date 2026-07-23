"""Hauptblock 6 media lifecycle, tenancy, worker, and immutable-version tests."""

import struct
import wave
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from backend.tests.integration.provider_helpers import add_user, login, setup_provider_context
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.domain.enums import (
    MediaApprovalStatus,
    MediaVerificationStatus,
    RetentionStatus,
    RightsReviewStatus,
    RoleName,
    TaskStatus,
)
from mediaos.domain.models import (
    AuditEvent,
    MediaAsset,
    MediaCollectionHistory,
    MediaFile,
    MediaRights,
    MediaTask,
    MediaVersion,
    Tenant,
)
from mediaos.infrastructure.object_storage import ObjectStorage
from mediaos.main import app
from mediaos.worker.media_processing import process_one_media_task

pytestmark = pytest.mark.integration


def png(width: int = 3, height: int = 2) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + struct.pack(">II", width, height)
        + bytes([8, 6, 0, 0, 0])
        + b"payload"
    )


def wav() -> bytes:
    output = BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 80)
    return output.getvalue()


def mp4(width: int = 640, height: int = 360) -> bytes:
    def box(kind: bytes, payload: bytes) -> bytes:
        return (len(payload) + 8).to_bytes(4, "big") + kind + payload

    ftyp = box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2")
    mvhd = box(
        b"mvhd",
        b"\x00\x00\x00\x00" + b"\x00" * 8 + (1000).to_bytes(4, "big") + (1000).to_bytes(4, "big"),
    )
    tkhd = box(
        b"tkhd",
        b"\x00" * 24 + (width << 16).to_bytes(4, "big") + (height << 16).to_bytes(4, "big"),
    )
    track = box(b"trak", tkhd + box(b"mdia", b"vide" + box(b"stsd", b"avc1")))
    return ftyp + box(b"moov", mvhd + track) + box(b"mdat", b"\x00")


async def upload(
    client: AsyncClient,
    csrf: str,
    *,
    title: str,
    filename: str,
    mime_type: str,
    content: bytes,
    key: str | None = None,
) -> object:
    return await client.post(
        "/api/v1/media-assets",
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": key or uuid4().hex},
        data={"title": title, "description": "Block-6 integration test"},
        files={"upload": (filename, content, mime_type)},
    )


async def cleanup_media_objects(session: AsyncSession, tenant_id: object) -> None:
    files = list(await session.scalars(select(MediaFile).where(MediaFile.tenant_id == tenant_id)))
    storage = ObjectStorage()
    for item in files:
        if item.storage_status.value != "DELETED":
            await storage.remove(bucket=item.bucket, object_key=item.object_key)


class TemporaryReadFailure(ObjectStorage):
    async def get_private(self, *, bucket: str, object_key: str) -> bytes:
        del bucket, object_key
        raise RuntimeError("temporary local object-storage read failure")


async def test_supported_uploads_validation_and_binary_deduplication(
    integration_session: AsyncSession, tenant: Tenant
) -> None:
    context = await setup_provider_context(integration_session, tenant)
    cases = [
        ("image.png", "image/png", png()),
        ("document.pdf", "application/pdf", b"%PDF-1.7\n1 0 obj<</Type /Page>>endobj\n%%EOF"),
        ("audio.wav", "audio/wav", wav()),
        ("audio.mp3", "audio/mpeg", b"\xff\xfb\x90\x64" + b"\x00" * 1000),
        ("video.mp4", "video/mp4", mp4()),
    ]
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            csrf = await login(client, context, context.backoffice)
            first_file_id = None
            for filename, mime_type, content in cases:
                response = await upload(
                    client,
                    csrf,
                    title=filename,
                    filename=filename,
                    mime_type=mime_type,
                    content=content,
                )
                assert response.status_code == 201, response.text
                assert response.json()["quarantined"] is False
                if filename == "image.png":
                    first_file_id = response.json()["file_id"]
            duplicate = await upload(
                client,
                csrf,
                title="Separate asset, same binary",
                filename="duplicate.png",
                mime_type="image/png",
                content=png(),
            )
            assert duplicate.status_code == 201
            assert duplicate.json()["duplicate_binary"] is True
            assert duplicate.json()["file_id"] == first_file_id
            replay_key = uuid4().hex
            first = await upload(
                client,
                csrf,
                title="Idempotent",
                filename="idempotent.png",
                mime_type="image/png",
                content=png(4, 4),
                key=replay_key,
            )
            replay = await upload(
                client,
                csrf,
                title="Idempotent",
                filename="idempotent.png",
                mime_type="image/png",
                content=png(4, 4),
                key=replay_key,
            )
            assert first.status_code == replay.status_code == 201
            assert first.json()["asset_id"] == replay.json()["asset_id"]
            assert replay.json()["replayed"] is True
            mismatch = await upload(
                client,
                csrf,
                title="Quarantine",
                filename="misleading.pdf",
                mime_type="application/pdf",
                content=png(5, 5),
            )
            assert mismatch.status_code == 201
            assert mismatch.json()["quarantined"] is True
            empty = await upload(
                client,
                csrf,
                title="Empty",
                filename="empty.png",
                mime_type="image/png",
                content=b"",
            )
            assert empty.status_code == 422
            html = await upload(
                client,
                csrf,
                title="HTML",
                filename="active.pdf",
                mime_type="application/pdf",
                content=b"<html><script>alert(1)</script></html>",
            )
            assert html.status_code == 422
        assert await integration_session.scalar(select(func.count(MediaAsset.id))) == 8
        assert await integration_session.scalar(select(func.count(MediaFile.id))) == 7
    finally:
        await cleanup_media_objects(integration_session, tenant.id)


async def test_media_lifecycle_versions_rights_relations_collections_and_access(
    integration_session: AsyncSession, tenant: Tenant
) -> None:
    context = await setup_provider_context(integration_session, tenant)
    transport = ASGITransport(app=app)
    try:
        async with (
            AsyncClient(transport=transport, base_url="http://test") as editor,
            AsyncClient(transport=transport, base_url="http://test") as reviewer,
            AsyncClient(transport=transport, base_url="http://test") as admin,
            AsyncClient(transport=transport, base_url="http://test") as anonymous,
        ):
            editor_csrf = await login(editor, context, context.backoffice)
            reviewer_csrf = await login(reviewer, context, context.reviewer)
            admin_csrf = await login(admin, context, context.admin)
            created = await upload(
                editor,
                editor_csrf,
                title="Titelbild",
                filename="title.png",
                mime_type="image/png",
                content=png(),
            )
            assert created.status_code == 201
            asset_id = created.json()["asset_id"]
            pending_verification = (await editor.get(f"/api/v1/media-assets/{asset_id}")).json()
            assert pending_verification["technical_status"] == "PENDING"
            stored_file = await integration_session.scalar(
                select(MediaFile)
                .join(MediaVersion, MediaVersion.media_file_id == MediaFile.id)
                .where(MediaVersion.media_asset_id == UUID(asset_id))
            )
            assert stored_file is not None
            assert stored_file.verification_status == MediaVerificationStatus.PENDING
            while await process_one_media_task():
                pass
            await integration_session.refresh(stored_file)
            assert stored_file.verification_status == MediaVerificationStatus.VERIFIED
            verified = (await editor.get(f"/api/v1/media-assets/{asset_id}")).json()
            assert verified["technical_status"] == "VERIFIED"
            assert (await anonymous.get(f"/api/v1/media-assets/{asset_id}")).status_code == 401
            category = await admin.post(
                "/api/v1/media-categories",
                headers={"X-CSRF-Token": admin_csrf},
                json={"name": "Kampagne", "slug": f"campaign-{uuid4().hex}"},
            )
            assert category.status_code == 200
            tag = await editor.post(
                "/api/v1/media-tags",
                headers={"X-CSRF-Token": editor_csrf},
                json={"name": f"Sommer-{uuid4().hex}", "synonyms": ["Summer"]},
            )
            detail = (await editor.get(f"/api/v1/media-assets/{asset_id}")).json()
            updated = await editor.patch(
                f"/api/v1/media-assets/{asset_id}",
                headers={"X-CSRF-Token": editor_csrf},
                json={
                    "expected_revision": detail["revision"],
                    "title": "Titelbild aktualisiert",
                    "description": "Fachliche Beschreibung",
                    "category_id": category.json()["id"],
                    "tag_ids": [tag.json()["id"]],
                    "business_metadata": {"campaign": "Sommer"},
                    "custom_metadata": {"source": "internal"},
                },
            )
            assert updated.status_code == 200
            stale = await editor.patch(
                f"/api/v1/media-assets/{asset_id}",
                headers={"X-CSRF-Token": editor_csrf},
                json={
                    "expected_revision": detail["revision"],
                    "title": "Stale",
                    "description": None,
                    "tag_ids": [],
                    "business_metadata": {},
                    "custom_metadata": {},
                },
            )
            assert stale.status_code == 409
            detail = (await editor.get(f"/api/v1/media-assets/{asset_id}")).json()
            rights = await editor.put(
                f"/api/v1/media-assets/{asset_id}/rights",
                headers={"X-CSRF-Token": editor_csrf},
                json={
                    "expected_revision": detail["revision"],
                    "rights_holder": "FUXX MEDIA Test",
                    "license_type": "INTERNAL",
                    "allowed_uses": ["INTERNAL"],
                    "allowed_regions": ["DE"],
                    "allowed_channels": ["INTERNAL"],
                },
            )
            assert rights.status_code == 200
            rights_review = await reviewer.post(
                f"/api/v1/media-assets/{asset_id}/rights/review",
                headers={"X-CSRF-Token": reviewer_csrf},
                json={"approve": True, "reason": "Rechte vollständig"},
            )
            assert rights_review.status_code == 200
            approval = await admin.post(
                f"/api/v1/media-assets/{asset_id}/approvals",
                headers={"X-CSRF-Token": admin_csrf},
                json={},
            )
            assert approval.status_code == 200
            requester_self_approval = await admin.post(
                f"/api/v1/media-assets/{asset_id}/approvals/{approval.json()['id']}/resolve",
                headers={"X-CSRF-Token": admin_csrf},
                json={"approve": True, "reason": "Must fail"},
            )
            assert requester_self_approval.status_code == 403
            creator_self_approval = await editor.post(
                f"/api/v1/media-assets/{asset_id}/approvals/{approval.json()['id']}/resolve",
                headers={"X-CSRF-Token": editor_csrf},
                json={"approve": True, "reason": "Uploader must not approve"},
            )
            assert creator_self_approval.status_code == 403
            approved = await reviewer.post(
                f"/api/v1/media-assets/{asset_id}/approvals/{approval.json()['id']}/resolve",
                headers={"X-CSRF-Token": reviewer_csrf},
                json={"approve": True, "reason": "Inhalt geprüft"},
            )
            assert approved.status_code == 200
            ready = (await editor.get(f"/api/v1/media-assets/{asset_id}")).json()
            assert ready["status"] == "READY"
            old_version = ready["versions"][0]
            new_version = await editor.post(
                f"/api/v1/media-assets/{asset_id}/versions",
                headers={"X-CSRF-Token": editor_csrf, "Idempotency-Key": uuid4().hex},
                data={"expected_revision": ready["revision"], "reason": "Neue Bildfassung"},
                files={"upload": ("title-v2.png", png(4, 3), "image/png")},
            )
            assert new_version.status_code == 201
            after_version = (await editor.get(f"/api/v1/media-assets/{asset_id}")).json()
            assert after_version["current_version_number"] == 2
            assert after_version["approval_status"] == "NOT_REQUESTED"
            assert after_version["technical_status"] == "PENDING"
            assert after_version["rights"]["review_status"] == "PENDING"
            stale_rights_approval = await admin.post(
                f"/api/v1/media-assets/{asset_id}/approvals",
                headers={"X-CSRF-Token": admin_csrf},
                json={},
            )
            assert stale_rights_approval.status_code == 422
            assert (
                next(item for item in after_version["versions"] if item["id"] == old_version["id"])[
                    "approval_status"
                ]
                == "APPROVED"
            )
            assert (
                await editor.get(
                    f"/api/v1/media-assets/{asset_id}/preview", headers={"Range": "bytes=0-7"}
                )
            ).status_code == 206
            assert (
                await anonymous.get(f"/api/v1/media-assets/{asset_id}/download")
            ).status_code == 401
            second = await upload(
                editor,
                editor_csrf,
                title="Zweites Medium",
                filename="second.png",
                mime_type="image/png",
                content=png(7, 5),
            )
            second_id = second.json()["asset_id"]
            relation = await editor.post(
                f"/api/v1/media-assets/{asset_id}/relations",
                headers={"X-CSRF-Token": editor_csrf},
                json={"target_asset_id": second_id, "relation_type": "LINKED_WITH"},
            )
            assert relation.status_code == 200
            cycle = await editor.post(
                f"/api/v1/media-assets/{second_id}/relations",
                headers={"X-CSRF-Token": editor_csrf},
                json={"target_asset_id": asset_id, "relation_type": "LINKED_WITH"},
            )
            assert cycle.status_code == 409
            collection = await editor.post(
                "/api/v1/media-collections",
                headers={"X-CSRF-Token": editor_csrf},
                json={"name": f"Campaign-{uuid4().hex}", "visibility": "TENANT"},
            )
            assert collection.status_code == 200
            assert (
                await editor.post(
                    f"/api/v1/media-collections/{collection.json()['id']}/items",
                    headers={"X-CSRF-Token": editor_csrf},
                    json={"asset_id": asset_id},
                )
            ).status_code == 200
            listed = await editor.get(
                "/api/v1/media-assets", params={"query": "Titelbild", "page_size": 1}
            )
            assert listed.status_code == 200
            assert listed.json()["total"] == 1
            assert listed.json()["page_size"] == 1
            deletion = await editor.post(
                f"/api/v1/media-assets/{asset_id}/deletion-requests",
                headers={"X-CSRF-Token": editor_csrf},
                json={"expected_revision": after_version["revision"], "reason": "Test"},
            )
            assert deletion.status_code == 200
            blocked = await admin.post(
                f"/api/v1/media-assets/{asset_id}/deletion-approvals",
                headers={"X-CSRF-Token": admin_csrf},
                json={"request_id": deletion.json()["id"], "reason": "Admin review"},
            )
            assert blocked.status_code == 422

            other_tenant = Tenant(name="Other media", slug=f"other-media-{uuid4().hex}")
            integration_session.add(other_tenant)
            await integration_session.flush()
            other_user = await add_user(
                integration_session, other_tenant, "other-media", RoleName.ADMIN
            )
            await integration_session.commit()
            other_context = type(context)(
                other_tenant, other_user, other_user, other_user, context.job
            )
            async with AsyncClient(transport=transport, base_url="http://test") as other:
                await login(other, other_context, other_user)
                assert (await other.get(f"/api/v1/media-assets/{asset_id}")).status_code == 404

        while await process_one_media_task():
            pass
        tasks = list(await integration_session.scalars(select(MediaTask)))
        assert tasks
        assert all(item.status == TaskStatus.SUCCEEDED for item in tasks)
        versions = list(
            await integration_session.scalars(
                select(MediaVersion).where(MediaVersion.media_asset_id == asset_id)
            )
        )
        assert len(versions) == 2
        assert sum(item.is_current for item in versions) == 1
        assert any(item.approval_status == MediaApprovalStatus.APPROVED for item in versions)
        event_types = set(await integration_session.scalars(select(AuditEvent.event_type)))
        assert {
            "MEDIA_ASSET_CREATED",
            "MEDIA_VERSION_CREATED",
            "MEDIA_RIGHTS_APPROVED",
            "MEDIA_APPROVED",
            "MEDIA_RELATION_CREATED",
            "MEDIA_DELETION_REQUESTED",
            "MEDIA_TASK_COMPLETED",
        }.issubset(event_types)
    finally:
        await cleanup_media_objects(integration_session, tenant.id)


async def test_media_negative_gates_taxonomy_collection_and_worker_recovery(
    integration_session: AsyncSession, tenant: Tenant
) -> None:
    context = await setup_provider_context(integration_session, tenant)
    reader_user = await add_user(integration_session, tenant, "media-reader", RoleName.READER)
    await integration_session.commit()
    reader_context = type(context)(tenant, reader_user, reader_user, reader_user, context.job)
    transport = ASGITransport(app=app)
    try:
        async with (
            AsyncClient(transport=transport, base_url="http://test") as editor,
            AsyncClient(transport=transport, base_url="http://test") as reviewer,
            AsyncClient(transport=transport, base_url="http://test") as admin,
            AsyncClient(transport=transport, base_url="http://test") as reader,
        ):
            editor_csrf = await login(editor, context, context.backoffice)
            reviewer_csrf = await login(reviewer, context, context.reviewer)
            admin_csrf = await login(admin, context, context.admin)
            await login(reader, reader_context, reader_user)

            forbidden_upload = await upload(
                reviewer,
                reviewer_csrf,
                title="Wrong role",
                filename="forbidden.png",
                mime_type="image/png",
                content=png(),
            )
            assert forbidden_upload.status_code == 403
            missing_csrf = await editor.post(
                "/api/v1/media-assets",
                headers={"Idempotency-Key": uuid4().hex},
                data={"title": "Missing CSRF"},
                files={"upload": ("missing.png", png(), "image/png")},
            )
            assert missing_csrf.status_code == 403

            created = await upload(
                editor,
                editor_csrf,
                title="Retention candidate",
                filename="retention.png",
                mime_type="image/png",
                content=png(8, 6),
            )
            assert created.status_code == 201
            asset_id = created.json()["asset_id"]
            detail = (await editor.get(f"/api/v1/media-assets/{asset_id}")).json()
            no_rights = await editor.post(
                f"/api/v1/media-assets/{asset_id}/approvals",
                headers={"X-CSRF-Token": editor_csrf},
            )
            assert no_rights.status_code == 422
            assert (await reader.get("/api/v1/media-assets")).json()["total"] == 0
            assert (await reader.get(f"/api/v1/media-assets/{asset_id}")).status_code == 404

            parent = await admin.post(
                "/api/v1/media-categories",
                headers={"X-CSRF-Token": admin_csrf},
                json={"name": "Parent", "slug": f"parent-{uuid4().hex}"},
            )
            child = await admin.post(
                "/api/v1/media-categories",
                headers={"X-CSRF-Token": admin_csrf},
                json={
                    "name": "Child",
                    "slug": f"child-{uuid4().hex}",
                    "parent_id": parent.json()["id"],
                },
            )
            tag = await editor.post(
                "/api/v1/media-tags",
                headers={"X-CSRF-Token": editor_csrf},
                json={"name": f"Inactive-{uuid4().hex}", "synonyms": ["disabled"]},
            )
            assert child.status_code == tag.status_code == 200
            assert (
                await admin.patch(
                    f"/api/v1/media-categories/{child.json()['id']}",
                    headers={"X-CSRF-Token": admin_csrf},
                    json={"active": False},
                )
            ).status_code == 200
            assert (
                await admin.patch(
                    f"/api/v1/media-tags/{tag.json()['id']}",
                    headers={"X-CSRF-Token": admin_csrf},
                    json={"active": False},
                )
            ).status_code == 200
            taxonomy = (await editor.get("/api/v1/media-taxonomy")).json()
            assert child.json()["id"] not in {item["id"] for item in taxonomy["categories"]}
            assert tag.json()["id"] not in {item["id"] for item in taxonomy["tags"]}
            inactive_assignment = await editor.patch(
                f"/api/v1/media-assets/{asset_id}",
                headers={"X-CSRF-Token": editor_csrf},
                json={
                    "expected_revision": detail["revision"],
                    "title": detail["title"],
                    "description": detail["description"],
                    "category_id": child.json()["id"],
                    "tag_ids": [tag.json()["id"]],
                    "business_metadata": {},
                    "custom_metadata": {},
                },
            )
            assert inactive_assignment.status_code == 404

            expired_at = datetime.now(UTC) - timedelta(days=1)
            expired_rights = await editor.put(
                f"/api/v1/media-assets/{asset_id}/rights",
                headers={"X-CSRF-Token": editor_csrf},
                json={
                    "expected_revision": detail["revision"],
                    "rights_holder": "Expired Rights Owner",
                    "license_type": "INTERNAL",
                    "usage_end": expired_at.isoformat(),
                    "allowed_uses": ["INTERNAL"],
                    "allowed_regions": ["DE"],
                    "allowed_channels": ["INTERNAL"],
                },
            )
            assert expired_rights.status_code == 200
            blocked_review = await reviewer.post(
                f"/api/v1/media-assets/{asset_id}/rights/review",
                headers={"X-CSRF-Token": reviewer_csrf},
                json={"approve": True, "reason": "Must remain expired"},
            )
            assert blocked_review.status_code == 422
            search = await editor.get(
                "/api/v1/media-assets",
                params={"query": "Expired Rights Owner", "rights_status": "EXPIRED"},
            )
            assert search.status_code == 200
            assert search.json()["total"] == 1

            second = await upload(
                editor,
                editor_csrf,
                title="Collection second",
                filename="collection.png",
                mime_type="image/png",
                content=png(9, 7),
            )
            second_id = second.json()["asset_id"]
            collection = await editor.post(
                "/api/v1/media-collections",
                headers={"X-CSRF-Token": editor_csrf},
                json={"name": f"Retention-{uuid4().hex}", "visibility": "TENANT"},
            )
            collection_id = collection.json()["id"]
            for member in (asset_id, second_id):
                assert (
                    await editor.post(
                        f"/api/v1/media-collections/{collection_id}/items",
                        headers={"X-CSRF-Token": editor_csrf},
                        json={"asset_id": member},
                    )
                ).status_code == 200
            assert (
                await editor.put(
                    f"/api/v1/media-collections/{collection_id}/order",
                    headers={"X-CSRF-Token": editor_csrf},
                    json={"asset_ids": [second_id, asset_id]},
                )
            ).status_code == 200
            assert (
                await editor.patch(
                    f"/api/v1/media-collections/{collection_id}",
                    headers={"X-CSRF-Token": editor_csrf},
                    json={
                        "name": f"Retention-updated-{uuid4().hex}",
                        "description": "Immutable collection history",
                        "visibility": "PRIVATE",
                        "status": "ACTIVE",
                    },
                )
            ).status_code == 200
            assert (
                await editor.delete(
                    f"/api/v1/media-collections/{collection_id}/items/{second_id}",
                    headers={"X-CSRF-Token": editor_csrf},
                )
            ).status_code == 200

            current = (await editor.get(f"/api/v1/media-assets/{asset_id}")).json()
            archived = await editor.post(
                f"/api/v1/media-assets/{asset_id}/archive",
                headers={"X-CSRF-Token": editor_csrf},
                json={"expected_revision": current["revision"]},
            )
            assert archived.status_code == 200
            deletion = await editor.post(
                f"/api/v1/media-assets/{asset_id}/deletion-requests",
                headers={"X-CSRF-Token": editor_csrf},
                json={
                    "expected_revision": archived.json()["revision"],
                    "reason": "Controlled purge test",
                },
            )
            assert deletion.status_code == 200
            referenced = await admin.post(
                f"/api/v1/media-assets/{asset_id}/deletion-approvals",
                headers={"X-CSRF-Token": admin_csrf},
                json={"request_id": deletion.json()["id"], "reason": "Reference check"},
            )
            assert referenced.status_code == 422
            assert (
                await editor.delete(
                    f"/api/v1/media-collections/{collection_id}/items/{asset_id}",
                    headers={"X-CSRF-Token": editor_csrf},
                )
            ).status_code == 200

        await integration_session.commit()
        assert await process_one_media_task(storage=TemporaryReadFailure()) is True
        retry_task = await integration_session.scalar(
            select(MediaTask).where(
                MediaTask.task_type == "VERIFY_MEDIA", MediaTask.status == TaskStatus.RETRY
            )
        )
        assert retry_task is not None
        await integration_session.refresh(retry_task)
        assert retry_task.status == TaskStatus.RETRY
        retry_task.available_at = datetime.now(UTC) - timedelta(seconds=1)
        await integration_session.commit()
        assert await process_one_media_task() is True
        while await process_one_media_task():
            pass

        preview_task = await integration_session.scalar(
            select(MediaTask).where(MediaTask.task_type == "REGISTER_PREVIEW").limit(1)
        )
        assert preview_task is not None
        preview_task.status = TaskStatus.RUNNING
        preview_task.attempts = 1
        preview_task.locked_at = datetime.now(UTC) - timedelta(minutes=10)
        preview_task.locked_by = "stale-worker"
        await integration_session.commit()
        assert await process_one_media_task() is True
        await integration_session.refresh(preview_task)
        assert preview_task.status == TaskStatus.SUCCEEDED

        premature = MediaTask(
            tenant_id=tenant.id,
            media_asset_id=UUID(asset_id),
            media_version_id=None,
            task_type="PURGE_MEDIA",
            payload={"external_effect": False, "test": "without-approval"},
        )
        integration_session.add(premature)
        await integration_session.commit()
        assert await process_one_media_task() is True
        await integration_session.refresh(premature)
        assert premature.status == TaskStatus.FAILED

        async with AsyncClient(transport=transport, base_url="http://test") as admin:
            admin_csrf = await login(admin, context, context.admin)
            approved = await admin.post(
                f"/api/v1/media-assets/{asset_id}/deletion-approvals",
                headers={"X-CSRF-Token": admin_csrf},
                json={"request_id": deletion.json()["id"], "reason": "Independent approval"},
            )
            assert approved.status_code == 200
        while await process_one_media_task():
            pass
        deleted = await integration_session.get(MediaAsset, UUID(asset_id))
        assert deleted is not None
        await integration_session.refresh(deleted)
        assert deleted.retention_status == RetentionStatus.PURGED
        assert await process_one_media_task() is False

        rights = await integration_session.scalar(
            select(MediaRights).where(MediaRights.media_asset_id == UUID(asset_id))
        )
        assert rights is not None and rights.review_status == RightsReviewStatus.EXPIRED
        assert await integration_session.scalar(select(func.count(MediaCollectionHistory.id))) >= 5
        event_types = set(await integration_session.scalars(select(AuditEvent.event_type)))
        assert {
            "MEDIA_RIGHTS_BLOCKED",
            "MEDIA_TASK_RETRY",
            "MEDIA_TASK_DEAD_LETTER",
            "MEDIA_PURGED",
            "MEDIA_COLLECTION_ITEM_REMOVED",
        }.issubset(event_types)
    finally:
        await cleanup_media_objects(integration_session, tenant.id)
