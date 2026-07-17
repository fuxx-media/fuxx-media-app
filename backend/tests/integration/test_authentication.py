"""Persistent session, expiry, revocation, CSRF, role, and tenant tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.domain.enums import RoleName
from mediaos.domain.models import AuthSession, Tenant, User, UserRole
from mediaos.main import app
from mediaos.security import hash_password

pytestmark = pytest.mark.integration
PASSWORD = "persistent-test-password"


async def create_user(
    session: AsyncSession, tenant: Tenant, role: RoleName, *, email: str | None = None
) -> User:
    user = User(
        tenant_id=tenant.id,
        email=email or f"user-{uuid4().hex}@example.com",
        password_hash=hash_password(PASSWORD),
    )
    session.add(user)
    await session.flush()
    session.add(UserRole(user_id=user.id, role=role))
    await session.commit()
    return user


async def login(client: AsyncClient, tenant: Tenant, user: User, password: str = PASSWORD):
    return await client.post(
        "/api/v1/auth/login",
        json={"tenant_slug": tenant.slug, "email": user.email, "password": password},
    )


async def test_login_success_and_failed_credentials(
    integration_session: AsyncSession, tenant: Tenant
) -> None:
    user = await create_user(integration_session, tenant, RoleName.ADMIN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        failed = await login(client, tenant, user, "incorrect-password-123")
        assert failed.status_code == 401
        assert failed.json()["code"] == "INVALID_CREDENTIALS"
        response = await login(client, tenant, user)
        assert response.status_code == 200
        assert response.cookies.get("mediaos_session")
        assert response.cookies.get("mediaos_csrf")
        assert "ADMIN" in response.json()["roles"]
        me = await client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["user_id"] == str(user.id)


async def test_session_expiry_and_logout_revocation(
    integration_session: AsyncSession, tenant: Tenant
) -> None:
    user = await create_user(integration_session, tenant, RoleName.ADMIN)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        logged_in = await login(client, tenant, user)
        csrf = logged_in.json()["csrf_token"]
        logout = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
        assert logout.status_code == 204
        assert (await client.get("/api/v1/auth/me")).status_code == 401

        await login(client, tenant, user)
        auth_session = await integration_session.scalar(
            select(AuthSession)
            .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
            .order_by(AuthSession.created_at.desc())
        )
        assert auth_session is not None
        auth_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await integration_session.commit()
        expired = await client.get("/api/v1/auth/me")
        assert expired.status_code == 401


async def test_csrf_role_and_tenant_boundaries(
    integration_session: AsyncSession, tenant: Tenant
) -> None:
    reviewer = await create_user(integration_session, tenant, RoleName.REVIEWER)
    other_tenant = Tenant(name="Other", slug=f"other-{uuid4().hex}")
    integration_session.add(other_tenant)
    await integration_session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        logged_in = await login(client, tenant, reviewer)
        csrf = logged_in.json()["csrf_token"]
        missing_csrf = await client.post(
            "/api/v1/channels",
            headers={"Idempotency-Key": uuid4().hex},
            json={"name": "No CSRF", "slug": "no-csrf"},
        )
        assert missing_csrf.status_code == 403
        assert missing_csrf.json()["code"] == "CSRF_VALIDATION_FAILED"
        forbidden_role = await client.post(
            "/api/v1/channels",
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": uuid4().hex},
            json={"name": "Reviewer", "slug": "reviewer"},
        )
        assert forbidden_role.status_code == 403
        assert forbidden_role.json()["code"] == "FORBIDDEN"
