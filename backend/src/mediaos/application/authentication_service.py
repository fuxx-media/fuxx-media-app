"""Persistent, provider-independent authentication and session lifecycle."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from mediaos.application.errors import AuthenticationError, InvalidCredentialsError
from mediaos.config import get_settings
from mediaos.domain.actor import Actor
from mediaos.domain.enums import ActorType, RoleName
from mediaos.domain.models import AuditEvent, AuthSession, Tenant, User
from mediaos.security import digest_secret, generate_secret, verify_password


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    actor: Actor
    email: str
    session_id: object
    session_token: str
    csrf_token: str
    expires_at: datetime


class AuthenticationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def login(self, *, tenant_slug: str, email: str, password: str) -> AuthenticatedSession:
        normalized_email = email.strip().lower()
        result = await self.session.execute(
            select(User)
            .join(Tenant, Tenant.id == User.tenant_id)
            .options(selectinload(User.roles))
            .where(
                Tenant.slug == tenant_slug.strip().lower(),
                Tenant.active.is_(True),
                User.email == normalized_email,
                User.active.is_(True),
            )
        )
        user = result.scalar_one_or_none()
        if user is None or not verify_password(user.password_hash, password):
            raise InvalidCredentialsError("Email, password, or tenant is invalid")

        now = datetime.now(UTC)
        session_token = generate_secret()
        csrf_token = generate_secret()
        auth_session = AuthSession(
            user_id=user.id,
            token_hash=digest_secret(session_token),
            csrf_token_hash=digest_secret(csrf_token),
            expires_at=now + timedelta(seconds=get_settings().mediaos_session_ttl_seconds),
            last_seen_at=now,
        )
        self.session.add(auth_session)
        await self.session.flush()
        roles = frozenset(role.role for role in user.roles)
        self.session.add(
            AuditEvent(
                tenant_id=user.tenant_id,
                actor_id=user.id,
                actor_type=ActorType.USER,
                event_type="LOGIN_SUCCEEDED",
                payload={"session_id": str(auth_session.id)},
            )
        )
        return AuthenticatedSession(
            actor=Actor(id=user.id, type=ActorType.USER, tenant_id=user.tenant_id, roles=roles),
            email=user.email,
            session_id=auth_session.id,
            session_token=session_token,
            csrf_token=csrf_token,
            expires_at=auth_session.expires_at,
        )

    async def authenticate(self, session_token: str) -> tuple[Actor, AuthSession, str]:
        now = datetime.now(UTC)
        result = await self.session.execute(
            select(AuthSession, User)
            .join(User, User.id == AuthSession.user_id)
            .join(Tenant, Tenant.id == User.tenant_id)
            .options(selectinload(User.roles))
            .where(
                AuthSession.token_hash == digest_secret(session_token),
                Tenant.active.is_(True),
            )
        )
        row = result.one_or_none()
        if row is None:
            raise AuthenticationError("A valid server session is required")
        auth_session, user = row
        if auth_session.revoked_at is not None or auth_session.expires_at <= now or not user.active:
            raise AuthenticationError("The server session is expired or revoked")
        auth_session.last_seen_at = now
        roles = frozenset(role.role for role in user.roles)
        return (
            Actor(id=user.id, type=ActorType.USER, tenant_id=user.tenant_id, roles=roles),
            auth_session,
            user.email,
        )

    async def revoke(self, auth_session: AuthSession, actor: Actor) -> None:
        auth_session.revoked_at = datetime.now(UTC)
        if actor.tenant_id is None:
            raise AuthenticationError("Authenticated user has no tenant")
        self.session.add(
            AuditEvent(
                tenant_id=actor.tenant_id,
                actor_id=actor.id,
                actor_type=actor.type,
                event_type="SESSION_REVOKED",
                payload={"session_id": str(auth_session.id)},
            )
        )


WRITE_ROLES = frozenset({RoleName.ADMIN, RoleName.BACKOFFICE})
REVIEW_ROLES = frozenset({RoleName.ADMIN, RoleName.BACKOFFICE, RoleName.REVIEWER})
