"""PostgreSQL-backed task queue with exclusive SKIP LOCKED claiming."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.domain.enums import TaskStatus
from mediaos.domain.models import JobTask


class QueueRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def claim_next(self, *, worker_id: str) -> JobTask | None:
        now = datetime.now(UTC)
        result = await self.session.execute(
            select(JobTask)
            .where(
                JobTask.status.in_([TaskStatus.PENDING, TaskStatus.RETRY]),
                JobTask.available_at <= now,
                JobTask.attempts < JobTask.max_attempts,
            )
            .order_by(JobTask.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        task = result.scalar_one_or_none()
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
            update(JobTask)
            .where(
                JobTask.status == TaskStatus.RUNNING,
                JobTask.locked_at < cutoff,
                JobTask.attempts >= JobTask.max_attempts,
            )
            .values(
                status=TaskStatus.FAILED,
                locked_at=None,
                locked_by=None,
                last_error="worker claim expired after final attempt",
            )
        )
        retryable = await self.session.execute(
            update(JobTask)
            .where(
                JobTask.status == TaskStatus.RUNNING,
                JobTask.locked_at < cutoff,
                JobTask.attempts < JobTask.max_attempts,
            )
            .values(
                status=TaskStatus.RETRY,
                locked_at=None,
                locked_by=None,
                available_at=datetime.now(UTC),
                last_error="worker claim expired before completion",
            )
        )
        terminal_count = int(getattr(terminal, "rowcount", 0) or 0)
        retryable_count = int(getattr(retryable, "rowcount", 0) or 0)
        return terminal_count + retryable_count

    async def complete(self, task_id: UUID) -> JobTask:
        task = await self._locked(task_id)
        task.status = TaskStatus.SUCCEEDED
        task.locked_at = None
        task.locked_by = None
        await self.session.flush()
        return task

    async def fail(self, task_id: UUID, *, error: str, retry_delay_seconds: int = 0) -> JobTask:
        task = await self._locked(task_id)
        task.last_error = error
        task.locked_at = None
        task.locked_by = None
        if task.attempts >= task.max_attempts:
            task.status = TaskStatus.FAILED
        else:
            task.status = TaskStatus.RETRY
            task.available_at = datetime.now(UTC) + timedelta(seconds=retry_delay_seconds)
        await self.session.flush()
        return task

    async def _locked(self, task_id: UUID) -> JobTask:
        result = await self.session.execute(
            select(JobTask).where(JobTask.id == task_id).with_for_update()
        )
        task = result.scalar_one()
        return task
