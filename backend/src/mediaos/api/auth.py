"""Minimal Phase 0 server-side authentication boundary."""

from typing import Annotated
from uuid import UUID

from fastapi import Header, HTTPException

from mediaos.domain.actor import Actor
from mediaos.domain.enums import ActorType


async def require_actor(
    actor_id: Annotated[str | None, Header(alias="X-Actor-Id")] = None,
    actor_type: Annotated[str | None, Header(alias="X-Actor-Type")] = None,
) -> Actor:
    if actor_id is None or actor_type is None:
        raise HTTPException(status_code=401, detail="Authenticated actor headers are required")
    try:
        return Actor(id=UUID(actor_id), type=ActorType(actor_type))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Actor headers are invalid") from exc
