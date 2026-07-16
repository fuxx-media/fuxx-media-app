"""Persistence repositories for the Phase 0 modular monolith."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.domain.models import Channel, ContentJob


class ChannelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, *, name: str, slug: str) -> Channel:
        channel = Channel(name=name, slug=slug)
        self.session.add(channel)
        await self.session.flush()
        return channel

    async def get(self, channel_id: UUID) -> Channel | None:
        return await self.session.get(Channel, channel_id)


class ContentJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, *, channel_id: UUID, title: str, budget_limit_cents: int) -> ContentJob:
        job = ContentJob(
            channel_id=channel_id,
            title=title,
            budget_limit_cents=budget_limit_cents,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get(self, job_id: UUID) -> ContentJob | None:
        return await self.session.get(ContentJob, job_id)

    async def get_for_update(self, job_id: UUID) -> ContentJob | None:
        result = await self.session.execute(
            select(ContentJob).where(ContentJob.id == job_id).with_for_update()
        )
        return result.scalar_one_or_none()
