"""Phase 2 tenant, claim, revision, approval, and audit integration tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.domain.enums import CasePriority, CaseStatus, RoleName
from mediaos.domain.models import (
    ApprovalRequest,
    AuditEvent,
    CaseRevision,
    Channel,
    ContentJob,
    InternalNote,
    Tenant,
    User,
    UserRole,
)
from mediaos.main import app
from mediaos.security import hash_password

pytestmark = pytest.mark.integration
PASSWORD = "phase-two-test-password"


async def create_user(session: AsyncSession, tenant: Tenant, *roles: RoleName) -> User:
    user = User(
        tenant_id=tenant.id,
        email=f"phase-two-{uuid4().hex}@example.com",
        password_hash=hash_password(PASSWORD),
    )
    session.add(user)
    await session.flush()
    session.add_all([UserRole(user_id=user.id, role=role) for role in roles])
    return user


async def create_job(
    session: AsyncSession, tenant: Tenant, title: str = "Phase 2 case"
) -> ContentJob:
    channel = Channel(tenant_id=tenant.id, name="Cases", slug=f"cases-{uuid4().hex}")
    session.add(channel)
    await session.flush()
    job = ContentJob(
        tenant_id=tenant.id,
        channel_id=channel.id,
        title=title,
        budget_limit_cents=0,
    )
    session.add(job)
    await session.flush()
    return job


async def login(client: AsyncClient, tenant: Tenant, user: User) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": tenant.slug, "email": user.email, "password": PASSWORD},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def write_headers(csrf: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf}


async def detail(client: AsyncClient, job_id: object) -> dict[str, object]:
    response = await client.get(f"/api/v1/cases/{job_id}")
    assert response.status_code == 200
    return response.json()


async def test_complete_revision_bound_four_eyes_workflow(
    integration_session: AsyncSession, tenant: Tenant
) -> None:
    backoffice = await create_user(integration_session, tenant, RoleName.ADMIN, RoleName.BACKOFFICE)
    reviewer = await create_user(integration_session, tenant, RoleName.REVIEWER)
    job = await create_job(integration_session, tenant)
    await integration_session.commit()

    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as backoffice_client,
        AsyncClient(transport=transport, base_url="http://test") as reviewer_client,
    ):
        backoffice_csrf = await login(backoffice_client, tenant, backoffice)
        reviewer_csrf = await login(reviewer_client, tenant, reviewer)
        headers = write_headers(backoffice_csrf)
        reviewer_headers = write_headers(reviewer_csrf)

        claimed = await backoffice_client.post(
            f"/api/v1/cases/{job.id}/claim", json={"expected_version": 1}, headers=headers
        )
        assert claimed.status_code == 200
        updated = await backoffice_client.post(
            f"/api/v1/cases/{job.id}/update",
            json={
                "expected_version": 1,
                "category": "invoice-check",
                "priority": "HIGH",
                "due_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            },
            headers=headers,
        )
        assert updated.status_code == 200
        assert updated.json()["version"] == 2

        checklist = await backoffice_client.post(
            f"/api/v1/cases/{job.id}/checklist",
            json={"expected_version": 2, "titles": ["Identity checked", "Document checked"]},
            headers=headers,
        )
        assert checklist.status_code == 200
        items = checklist.json()["items"]
        blocked = await backoffice_client.post(
            f"/api/v1/cases/{job.id}/approval-requests",
            json={"expected_version": 3},
            headers=headers,
        )
        assert blocked.status_code == 422
        for expected_version, item in zip((3, 4), items, strict=True):
            completed = await backoffice_client.post(
                f"/api/v1/cases/{job.id}/checklist/{item['id']}",
                json={"expected_version": expected_version, "completed": True},
                headers=headers,
            )
            assert completed.status_code == 200

        note = await backoffice_client.post(
            f"/api/v1/cases/{job.id}/notes",
            json={"expected_version": 5, "content": "Immutable internal assessment."},
            headers=headers,
        )
        assert note.status_code == 200
        evidence = await backoffice_client.post(
            f"/api/v1/cases/{job.id}/evidence",
            json={
                "expected_version": 6,
                "source": "manual verification",
                "structured_data": {"reference": "verified-1"},
            },
            headers=headers,
        )
        assert evidence.status_code == 200

        requested = await backoffice_client.post(
            f"/api/v1/cases/{job.id}/approval-requests",
            json={"expected_version": 7},
            headers=headers,
        )
        assert requested.status_code == 200
        approval_id = requested.json()["id"]
        self_approval = await backoffice_client.post(
            f"/api/v1/cases/approvals/{approval_id}/resolve",
            json={"approved": True},
            headers=headers,
        )
        assert self_approval.status_code == 409
        reviewer_claim = await reviewer_client.post(
            f"/api/v1/cases/approvals/{approval_id}/claim", headers=reviewer_headers
        )
        assert reviewer_claim.status_code == 200
        missing_reason = await reviewer_client.post(
            f"/api/v1/cases/approvals/{approval_id}/resolve",
            json={"approved": False},
            headers=reviewer_headers,
        )
        assert missing_reason.status_code == 409
        rejected = await reviewer_client.post(
            f"/api/v1/cases/approvals/{approval_id}/resolve",
            json={"approved": False, "reason": "Correction required"},
            headers=reviewer_headers,
        )
        assert rejected.status_code == 200

        corrected = await backoffice_client.post(
            f"/api/v1/cases/{job.id}/update",
            json={"expected_version": 7, "category": "invoice-corrected", "priority": "HIGH"},
            headers=headers,
        )
        assert corrected.status_code == 200
        second_request = await backoffice_client.post(
            f"/api/v1/cases/{job.id}/approval-requests",
            json={"expected_version": 8},
            headers=headers,
        )
        second_approval_id = second_request.json()["id"]
        approved = await reviewer_client.post(
            f"/api/v1/cases/approvals/{second_approval_id}/resolve",
            json={"approved": True},
            headers=reviewer_headers,
        )
        assert approved.status_code == 200

        changed_after_approval = await backoffice_client.post(
            f"/api/v1/cases/{job.id}/update",
            json={"expected_version": 8, "category": "invoice-final", "priority": "URGENT"},
            headers=headers,
        )
        assert changed_after_approval.status_code == 200
        state = await detail(backoffice_client, job.id)
        approvals = state["approvals"]
        assert isinstance(approvals, list)
        assert next(item for item in approvals if item["id"] == second_approval_id)[
            "invalidated_at"
        ]

        final_request = await backoffice_client.post(
            f"/api/v1/cases/{job.id}/approval-requests",
            json={"expected_version": 9},
            headers=headers,
        )
        final_approval_id = final_request.json()["id"]
        final_approved = await reviewer_client.post(
            f"/api/v1/cases/approvals/{final_approval_id}/resolve",
            json={"approved": True},
            headers=reviewer_headers,
        )
        assert final_approved.status_code == 200
        closed = await backoffice_client.post(
            f"/api/v1/cases/{job.id}/close",
            json={"expected_version": 9, "reason": "Internal review completed"},
            headers=headers,
        )
        assert closed.status_code == 200
        assert closed.json()["business_status"] == CaseStatus.COMPLETED.value

    assert await integration_session.scalar(select(func.count(CaseRevision.id))) == 8
    assert await integration_session.scalar(select(func.count(ApprovalRequest.id))) == 3
    event_types = set((await integration_session.scalars(select(AuditEvent.event_type))).all())
    assert {
        "CASE_CLAIMED",
        "CHECKLIST_GENERATED",
        "INTERNAL_NOTE_ADDED",
        "EVIDENCE_ADDED",
        "APPROVAL_REJECTED",
        "APPROVAL_GRANTED",
        "CASE_COMPLETED",
    }.issubset(event_types)
    stored_note = await integration_session.scalar(select(InternalNote))
    assert stored_note is not None
    with pytest.raises(DBAPIError):
        await integration_session.execute(
            update(InternalNote).where(InternalNote.id == stored_note.id).values(content="changed")
        )
    await integration_session.rollback()


async def test_claim_conflict_expiry_optimistic_locking_role_and_tenant_lists(
    integration_session: AsyncSession, tenant: Tenant
) -> None:
    first_user = await create_user(integration_session, tenant, RoleName.BACKOFFICE)
    second_user = await create_user(integration_session, tenant, RoleName.BACKOFFICE)
    reviewer = await create_user(integration_session, tenant, RoleName.REVIEWER)
    first_job = await create_job(integration_session, tenant, "Visible urgent")
    first_job.priority = CasePriority.URGENT
    await create_job(integration_session, tenant, "Second visible")
    other_tenant = Tenant(name="Other", slug=f"other-{uuid4().hex}")
    integration_session.add(other_tenant)
    await integration_session.flush()
    await create_job(integration_session, other_tenant, "Must stay hidden")
    await integration_session.commit()

    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as first_client,
        AsyncClient(transport=transport, base_url="http://test") as second_client,
        AsyncClient(transport=transport, base_url="http://test") as reviewer_client,
    ):
        first_csrf = await login(first_client, tenant, first_user)
        second_csrf = await login(second_client, tenant, second_user)
        reviewer_csrf = await login(reviewer_client, tenant, reviewer)
        claimed = await first_client.post(
            f"/api/v1/cases/{first_job.id}/claim",
            json={"expected_version": 1},
            headers=write_headers(first_csrf),
        )
        assert claimed.status_code == 200
        conflict = await second_client.post(
            f"/api/v1/cases/{first_job.id}/claim",
            json={"expected_version": 1},
            headers=write_headers(second_csrf),
        )
        assert conflict.status_code == 409
        stale = await first_client.post(
            f"/api/v1/cases/{first_job.id}/update",
            json={"expected_version": 2, "category": "stale"},
            headers=write_headers(first_csrf),
        )
        assert stale.status_code == 409
        forbidden = await reviewer_client.post(
            f"/api/v1/cases/{first_job.id}/update",
            json={"expected_version": 1, "category": "forbidden"},
            headers=write_headers(reviewer_csrf),
        )
        assert forbidden.status_code == 403

        await integration_session.execute(
            update(ContentJob)
            .where(ContentJob.id == first_job.id)
            .values(claim_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await integration_session.commit()
        takeover = await second_client.post(
            f"/api/v1/cases/{first_job.id}/claim",
            json={"expected_version": 1},
            headers=write_headers(second_csrf),
        )
        assert takeover.status_code == 200
        assert takeover.json()["claimed_by"] == str(second_user.id)

        listing = await first_client.get("/api/v1/cases?page=1&page_size=1")
        assert listing.status_code == 200
        assert listing.json()["total"] == 2
        assert len(listing.json()["items"]) == 1
        urgent = await first_client.get("/api/v1/cases?priority=URGENT&search=Visible")
        assert urgent.status_code == 200
        assert urgent.json()["total"] == 1
        assert urgent.json()["items"][0]["tenant_id"] == str(tenant.id)
