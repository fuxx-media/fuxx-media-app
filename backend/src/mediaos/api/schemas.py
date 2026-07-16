"""Validated API request and response contracts."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from mediaos.domain.enums import ActorType, WorkflowState


class ChannelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=100)


class ChannelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    slug: str
    active: bool
    created_at: datetime


class ContentJobCreate(BaseModel):
    channel_id: UUID
    title: str = Field(min_length=1, max_length=300)
    budget_limit_cents: int = Field(ge=0)


class ContentJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    channel_id: UUID
    title: str
    current_state: WorkflowState
    version: int
    budget_limit_cents: int
    spent_cents: int
    created_at: datetime
    updated_at: datetime


class TransitionRequest(BaseModel):
    target_state: WorkflowState
    reason: str | None = Field(default=None, max_length=2000)
    expected_version: int = Field(ge=1)


class TransitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    from_state: WorkflowState
    to_state: WorkflowState
    actor_id: UUID
    actor_type: ActorType
    reason: str | None
    job_version: int
    created_at: datetime


class AuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    actor_id: UUID
    actor_type: ActorType
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


class CostResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    category: str
    amount_cents: int
    description: str | None
    created_at: datetime
