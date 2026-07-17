"""Shared Phase 3 integration-test setup."""

from dataclasses import dataclass
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.domain.enums import ApprovalStatus, CaseStatus, RoleName
from mediaos.domain.models import (
    ApprovalRequest,
    Channel,
    ContentJob,
    Tenant,
    User,
    UserRole,
)
from mediaos.security import hash_password

PASSWORD = "phase-three-test-password"


@dataclass(frozen=True, slots=True)
class ProviderContext:
    tenant: Tenant
    admin: User
    backoffice: User
    reviewer: User
    job: ContentJob


async def add_user(
    session: AsyncSession, tenant: Tenant, prefix: str, *roles: RoleName
) -> User:
    user = User(
        tenant_id=tenant.id,
        email=f"{prefix}-{uuid4().hex}@example.com",
        password_hash=hash_password(PASSWORD),
    )
    session.add(user)
    await session.flush()
    session.add_all([UserRole(user_id=user.id, role=role) for role in roles])
    return user


async def create_approved_job(
    session: AsyncSession,
    tenant: Tenant,
    backoffice: User,
    reviewer: User,
    *,
    title: str = "Approved provider case",
    category: str | None = "invoice-check",
) -> ContentJob:
    channel = Channel(tenant_id=tenant.id, name="Provider", slug=f"provider-{uuid4().hex}")
    session.add(channel)
    await session.flush()
    job = ContentJob(
        tenant_id=tenant.id,
        channel_id=channel.id,
        title=title,
        category=category,
        business_status=CaseStatus.APPROVED,
        budget_limit_cents=0,
        last_material_actor_id=backoffice.id,
    )
    session.add(job)
    await session.flush()
    session.add(
        ApprovalRequest(
            job_id=job.id,
            status=ApprovalStatus.APPROVED,
            requested_by=backoffice.id,
            resolved_by=reviewer.id,
            job_revision=job.version,
        )
    )
    await session.flush()
    return job


async def setup_provider_context(session: AsyncSession, tenant: Tenant) -> ProviderContext:
    admin = await add_user(session, tenant, "provider-admin", RoleName.ADMIN)
    backoffice = await add_user(session, tenant, "provider-backoffice", RoleName.BACKOFFICE)
    reviewer = await add_user(session, tenant, "provider-reviewer", RoleName.REVIEWER)
    job = await create_approved_job(session, tenant, backoffice, reviewer)
    await session.commit()
    return ProviderContext(tenant, admin, backoffice, reviewer, job)


async def login(client: AsyncClient, context: ProviderContext, user: User) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "tenant_slug": context.tenant.slug,
            "email": user.email,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


async def configure_provider(
    client: AsyncClient, csrf: str, *, name: str | None = None
) -> tuple[dict[str, object], str, str]:
    response = await client.post(
        "/api/v1/providers/simulation",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": name or f"Simulation {uuid4().hex}",
            "secret_reference_name": f"simulation-secret-{uuid4().hex}",
            "secret_environment_variable": "MEDIAOS_SIMULATION_CALLBACK_SECRET",
            "signature_profile_name": f"simulation-signature-{uuid4().hex}",
            "capability_operation": "SIMULATE_CASE",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    return payload, str(payload["id"]), str(payload["capabilities"][0]["id"])
