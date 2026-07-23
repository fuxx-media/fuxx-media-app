"""PostgreSQL media-task queue with exclusive claims and persistent retries."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.domain.enums import TaskStatus
from mediaos.domain.models import MediaTask


class MediaTaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def claim_next(self, *, worker_id: str) -> MediaTask | None:
        now = datetime.now(UTC)
        task = await self.session.scalar(
            select(MediaTask)
            .where(
                MediaTask.status.in_([TaskStatus.PENDING, TaskStatus.RETRY]),
                MediaTask.available_at <= now,
                MediaTask.attempts < MediaTask.max_attempts,
            )
            .order_by(MediaTask.created_at, MediaTask.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if task is None:
            return None
        task.status = TaskStatus.RUNNING
        task.attempts += 1
        task.locked_at = now
        task.locked_by = worker_id
        await self.session.flush()
        return task

    async def recover_stale(self, *, timeout_seconds: int = 300) -> int:
        cutoff = datetime.now(UTC) - timedelta(seconds=timeout_seconds)
        terminal = await self.session.execute(
            update(MediaTask)
            .where(
                MediaTask.status == TaskStatus.RUNNING,
                MediaTask.locked_at < cutoff,
                MediaTask.attempts >= MediaTask.max_attempts,
            )
            .values(
                status=TaskStatus.FAILED,
                locked_at=None,
                locked_by=None,
                last_error="media worker claim expired after final attempt",
            )
        )
        retryable = await self.session.execute(
            update(MediaTask)
            .where(
                MediaTask.status == TaskStatus.RUNNING,
                MediaTask.locked_at < cutoff,
                MediaTask.attempts < MediaTask.max_attempts,
            )
            .values(
                status=TaskStatus.RETRY,
                locked_at=None,
                locked_by=None,
                available_at=datetime.now(UTC),
                last_error="media worker claim expired before completion",
            )
        )
        return int(getattr(terminal, "rowcount", 0) or 0) + int(
            getattr(retryable, "rowcount", 0) or 0
        )

    async def complete(self, task_id: UUID) -> MediaTask:
        task = await self._locked(task_id)
        task.status = TaskStatus.SUCCEEDED
        task.locked_at = None
        task.locked_by = None
        await self.session.flush()
        return task

    async def fail(
        self,
        task_id: UUID,
        *,
        error: str,
        permanent: bool,
        retry_delay_seconds: int = 5,
    ) -> MediaTask:
        task = await self._locked(task_id)
        task.last_error = error[:2000]
        task.locked_at = None
        task.locked_by = None
        if permanent or task.attempts >= task.max_attempts:
            task.status = TaskStatus.FAILED
        else:
            task.status = TaskStatus.RETRY
            task.available_at = datetime.now(UTC) + timedelta(seconds=retry_delay_seconds)
        await self.session.flush()
        return task

    async def _locked(self, task_id: UUID) -> MediaTask:
        task = await self.session.scalar(
            select(MediaTask).where(MediaTask.id == task_id).with_for_update()
        )
        if task is None:
            raise LookupError("Media task was not found")
        return task
