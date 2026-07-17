"""Explicit local administration commands; no default credentials are embedded."""

import argparse
import asyncio
import os

from sqlalchemy import select

from mediaos.database import close_engine, get_session_factory
from mediaos.domain.enums import RoleName
from mediaos.domain.models import Tenant, User, UserRole
from mediaos.security import hash_password


async def create_local_user(
    *, tenant_slug: str, tenant_name: str, email: str, role: RoleName
) -> None:
    password = os.getenv("MEDIAOS_BOOTSTRAP_PASSWORD")
    if password is None:
        raise RuntimeError("MEDIAOS_BOOTSTRAP_PASSWORD must be supplied for this one command")
    normalized_email = email.strip().lower()
    async with get_session_factory()() as session, session.begin():
        tenant = await session.scalar(select(Tenant).where(Tenant.slug == tenant_slug))
        if tenant is None:
            tenant = Tenant(name=tenant_name, slug=tenant_slug)
            session.add(tenant)
            await session.flush()
        user = await session.scalar(
            select(User).where(User.tenant_id == tenant.id, User.email == normalized_email)
        )
        if user is None:
            user = User(
                tenant_id=tenant.id,
                email=normalized_email,
                password_hash=hash_password(password),
            )
            session.add(user)
            await session.flush()
        existing_role = await session.get(UserRole, (user.id, role))
        if existing_role is None:
            session.add(UserRole(user_id=user.id, role=role))
        print(f"local user ready: tenant={tenant.slug} email={user.email} role={role.value}")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create-local-user")
    create.add_argument("--tenant-slug", required=True)
    create.add_argument("--tenant-name", required=True)
    create.add_argument("--email", required=True)
    create.add_argument("--role", choices=[role.value for role in RoleName], required=True)
    args = parser.parse_args()

    async def run_command() -> None:
        try:
            await create_local_user(
                tenant_slug=args.tenant_slug,
                tenant_name=args.tenant_name,
                email=args.email,
                role=RoleName(args.role),
            )
        finally:
            await close_engine()

    asyncio.run(run_command())


if __name__ == "__main__":
    main()
