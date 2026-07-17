"""Authenticated workflow actor."""

from dataclasses import dataclass
from uuid import UUID

from mediaos.domain.enums import ActorType, RoleName


@dataclass(frozen=True, slots=True)
class Actor:
    id: UUID
    type: ActorType
    tenant_id: UUID | None = None
    roles: frozenset[RoleName] = frozenset()
