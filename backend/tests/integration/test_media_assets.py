"""Hauptblock 6 media lifecycle, tenancy, worker, and immutable-version tests."""

import struct
import wave
from io import BytesIO
from uuid import uuid4

import pytest
from backend.tests.integration.provider_helpers import add_user, login, setup_provider_context
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.domain.enums import MediaApprovalStatus, RoleName, TaskStatus
from mediaos.domain.models import (
    AuditEvent,
    MediaAsset,
    MediaFile,
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


async def test_supported_uploads_validation_and_binary_deduplication(
    integration_session: AsyncSession, tenant: Tenant
) -> None:
    context = await setup_provider_context(integration_session, tenant)
    cases = [
        ("image.png", "image/png", png()),
        ("document.pdf", "application/pdf", b"%PDF-1.7\n1 0 obj<</Type /Page>>endobj\n%%EOF"),
        ("audio.wav", "audio/wav", wav()),
        ("audio.mp3", "audio/mpeg", b"\xff\xfb\x90\x64" + b"\x00" * 1000),
        ("video.mp4", "video/mp4", b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2"),
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
            approval = await editor.post(
                f"/api/v1/media-assets/{asset_id}/approvals",
                headers={"X-CSRF-Token": editor_csrf},
                json={},
            )
            assert approval.status_code == 200
            self_approval = await editor.post(
                f"/api/v1/media-assets/{asset_id}/approvals/{approval.json()['id']}/resolve",
                headers={"X-CSRF-Token": editor_csrf},
                json={"approve": True, "reason": "Must fail"},
            )
            assert self_approval.status_code == 403
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
