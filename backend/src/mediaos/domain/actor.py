"""Authenticated workflow actor."""

from dataclasses import dataclass
from uuid import UUID

from mediaos.domain.enums import ActorType


@dataclass(frozen=True, slots=True)
class Actor:
    id: UUID
    type: ActorType
