"""Login, session inspection, logout, and revocation routes."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.api.auth import SessionContext, require_csrf_context, require_session_context
from mediaos.application.authentication_service import AuthenticationService
from mediaos.config import get_settings
from mediaos.database import get_session
from mediaos.domain.enums import RoleName

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
Session = Annotated[AsyncSession, Depends(get_session)]


class LoginRequest(BaseModel):
    tenant_slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    email: EmailStr
    password: str = Field(min_length=12, max_length=1024)


class LoginResponse(BaseModel):
    user_id: UUID
    tenant_id: UUID
    email: str
    roles: list[RoleName]
    expires_at: datetime
    csrf_token: str


class MeResponse(BaseModel):
    user_id: UUID
    tenant_id: UUID
    email: str
    roles: list[RoleName]


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, response: Response, session: Session) -> LoginResponse:
    async with session.begin():
        result = await AuthenticationService(session).login(
            tenant_slug=body.tenant_slug,
            email=str(body.email),
            password=body.password,
        )
    if result.actor.tenant_id is None:
        raise RuntimeError("Authenticated browser user has no tenant")
    secure = get_settings().mediaos_cookie_secure
    max_age = get_settings().mediaos_session_ttl_seconds
    response.set_cookie(
        "mediaos_session",
        result.session_token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        "mediaos_csrf",
        result.csrf_token,
        max_age=max_age,
        httponly=False,
        secure=secure,
        samesite="strict",
        path="/",
    )
    return LoginResponse(
        user_id=result.actor.id,
        tenant_id=result.actor.tenant_id,
        email=result.email,
        roles=sorted(result.actor.roles, key=lambda role: role.value),
        expires_at=result.expires_at,
        csrf_token=result.csrf_token,
    )


@router.get("/me", response_model=MeResponse)
async def me(
    context: Annotated[SessionContext, Depends(require_session_context)],
) -> MeResponse:
    if context.actor.tenant_id is None:
        raise RuntimeError("Authenticated browser user has no tenant")
    return MeResponse(
        user_id=context.actor.id,
        tenant_id=context.actor.tenant_id,
        email=context.email,
        roles=sorted(context.actor.roles, key=lambda role: role.value),
    )


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    session: Session,
    context: Annotated[SessionContext, Depends(require_csrf_context)],
) -> Response:
    async with session.begin():
        await AuthenticationService(session).revoke(context.auth_session, context.actor)
    response.delete_cookie("mediaos_session", path="/")
    response.delete_cookie("mediaos_csrf", path="/")
    response.status_code = 204
    return response
