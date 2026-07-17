"""Persistence repositories for the Phase 0 modular monolith."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.domain.models import Channel, ContentJob


class ChannelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, *, tenant_id: UUID, name: str, slug: str) -> Channel:
        channel = Channel(tenant_id=tenant_id, name=name, slug=slug)
        self.session.add(channel)
        await self.session.flush()
        return channel

    async def get(self, channel_id: UUID, *, tenant_id: UUID | None = None) -> Channel | None:
        query = select(Channel).where(Channel.id == channel_id)
        if tenant_id is not None:
            query = query.where(Channel.tenant_id == tenant_id)
        return (await self.session.execute(query)).scalar_one_or_none()


class ContentJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, *, tenant_id: UUID, channel_id: UUID, title: str, budget_limit_cents: int
    ) -> ContentJob:
        job = ContentJob(
            tenant_id=tenant_id,
            channel_id=channel_id,
            title=title,
            budget_limit_cents=budget_limit_cents,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get(self, job_id: UUID, *, tenant_id: UUID | None = None) -> ContentJob | None:
        query = select(ContentJob).where(ContentJob.id == job_id)
        if tenant_id is not None:
            query = query.where(ContentJob.tenant_id == tenant_id)
        return (await self.session.execute(query)).scalar_one_or_none()

    async def get_for_update(
        self, job_id: UUID, *, tenant_id: UUID | None = None
    ) -> ContentJob | None:
        query = select(ContentJob).where(ContentJob.id == job_id)
        if tenant_id is not None:
            query = query.where(ContentJob.tenant_id == tenant_id)
        result = await self.session.execute(query.with_for_update())
        return result.scalar_one_or_none()
