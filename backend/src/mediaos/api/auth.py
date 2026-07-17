"""Server-side session, CSRF, role, and tenant authentication dependencies."""

import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import Cookie, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.application.authentication_service import (
    REVIEW_ROLES,
    WRITE_ROLES,
    AuthenticationService,
)
from mediaos.application.errors import AuthenticationError, AuthorizationError, CsrfError
from mediaos.database import get_session
from mediaos.domain.actor import Actor
from mediaos.domain.models import AuthSession
from mediaos.security import digest_secret


@dataclass(frozen=True, slots=True)
class SessionContext:
    actor: Actor
    auth_session: AuthSession
    email: str


async def require_session_context(
    session: Annotated[AsyncSession, Depends(get_session)],
    session_token: Annotated[str | None, Cookie(alias="mediaos_session")] = None,
) -> SessionContext:
    if not session_token:
        raise AuthenticationError("A valid server session is required")
    actor, auth_session, email = await AuthenticationService(session).authenticate(session_token)
    await session.commit()
    return SessionContext(actor=actor, auth_session=auth_session, email=email)


async def require_csrf_context(
    context: Annotated[SessionContext, Depends(require_session_context)],
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    csrf_cookie: Annotated[str | None, Cookie(alias="mediaos_csrf")] = None,
) -> SessionContext:
    if not csrf_header or not csrf_cookie or not hmac.compare_digest(csrf_header, csrf_cookie):
        raise CsrfError("CSRF token is missing or does not match the browser cookie")
    if not hmac.compare_digest(digest_secret(csrf_header), context.auth_session.csrf_token_hash):
        raise CsrfError("CSRF token is invalid")
    return context


async def require_actor(
    context: Annotated[SessionContext, Depends(require_session_context)],
) -> Actor:
    return context.actor


async def require_write_actor(
    context: Annotated[SessionContext, Depends(require_csrf_context)],
) -> Actor:
    if context.actor.roles.isdisjoint(WRITE_ROLES):
        raise AuthorizationError("Admin or Backoffice role is required")
    return context.actor


async def require_review_actor(
    context: Annotated[SessionContext, Depends(require_csrf_context)],
) -> Actor:
    if context.actor.roles.isdisjoint(REVIEW_ROLES):
        raise AuthorizationError("Admin, Backoffice, or Reviewer role is required")
    return context.actor
