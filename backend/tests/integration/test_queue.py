"""PostgreSQL queue locking, retry, success, and terminal failure tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from mediaos.database import get_session_factory
from mediaos.domain.enums import TaskStatus
from mediaos.domain.models import Channel, ContentJob, JobTask, Tenant
from mediaos.infrastructure.queue_repository import QueueRepository

pytestmark = pytest.mark.integration


async def test_skip_locked_success_retry_and_max_attempts(
    integration_session: AsyncSession, tenant: Tenant
) -> None:
    async with integration_session.begin():
        channel = Channel(tenant_id=tenant.id, name="Queue", slug=f"queue-{uuid4().hex}")
        integration_session.add(channel)
        await integration_session.flush()
        job = ContentJob(
            tenant_id=tenant.id,
            channel_id=channel.id,
            title="Queue",
            budget_limit_cents=0,
        )
        integration_session.add(job)
        await integration_session.flush()
        created_at = datetime.now(UTC)
        first = JobTask(
            job_id=job.id,
            task_type="HEARTBEAT",
            max_attempts=2,
            created_at=created_at,
        )
        second = JobTask(
            job_id=job.id,
            task_type="FAIL",
            max_attempts=1,
            created_at=created_at + timedelta(seconds=1),
        )
        integration_session.add_all([first, second])

    factory = get_session_factory()
    async with factory() as session_one, factory() as session_two:
        async with session_one.begin():
            claimed_first = await QueueRepository(session_one).claim_next(worker_id="one")
            assert claimed_first is not None
            async with session_two.begin():
                claimed_second = await QueueRepository(session_two).claim_next(worker_id="two")
                assert claimed_second is not None
                assert claimed_second.id != claimed_first.id
                assert claimed_second.max_attempts == 1
                assert claimed_second.attempts == 1
                terminal = await QueueRepository(session_two).fail(
                    claimed_second.id, error="terminal"
                )
                assert terminal.status == TaskStatus.FAILED
        async with session_one.begin():
            completed = await QueueRepository(session_one).complete(claimed_first.id)
            assert completed.status == TaskStatus.SUCCEEDED

    async with integration_session.begin():
        retry_task = JobTask(job_id=job.id, task_type="RETRY", max_attempts=2)
        integration_session.add(retry_task)
    async with integration_session.begin():
        claimed = await QueueRepository(integration_session).claim_next(worker_id="retry")
        assert claimed is not None
        retried = await QueueRepository(integration_session).fail(claimed.id, error="retry")
        assert retried.status == TaskStatus.RETRY


async def test_worker_restart_recovers_stale_claim_and_preserves_terminal_failure(
    integration_session: AsyncSession, tenant: Tenant
) -> None:
    async with integration_session.begin():
        channel = Channel(tenant_id=tenant.id, name="Recovery", slug=f"recovery-{uuid4().hex}")
        integration_session.add(channel)
        await integration_session.flush()
        job = ContentJob(
            tenant_id=tenant.id,
            channel_id=channel.id,
            title="Recovery",
            budget_limit_cents=0,
        )
        integration_session.add(job)
        await integration_session.flush()
        retryable = JobTask(job_id=job.id, task_type="RECOVER", max_attempts=2)
        terminal = JobTask(job_id=job.id, task_type="TERMINAL", max_attempts=1)
        integration_session.add_all([retryable, terminal])
    async with integration_session.begin():
        first = await QueueRepository(integration_session).claim_next(worker_id="dead-worker")
        second = await QueueRepository(integration_session).claim_next(worker_id="dead-worker")
        assert first is not None and second is not None
        first.locked_at = datetime.now(UTC) - timedelta(minutes=10)
        second.locked_at = datetime.now(UTC) - timedelta(minutes=10)
    async with integration_session.begin():
        recovered = await QueueRepository(integration_session).recover_stale(timeout_seconds=60)
        assert recovered == 2
    await integration_session.refresh(retryable)
    await integration_session.refresh(terminal)
    statuses = {retryable.status, terminal.status}
    assert statuses == {TaskStatus.RETRY, TaskStatus.FAILED}
