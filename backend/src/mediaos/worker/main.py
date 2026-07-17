"""Phase 0 PostgreSQL queue worker and readiness heartbeat."""

import asyncio
import logging
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from mediaos.database import close_engine, database_ready, get_session_factory
from mediaos.domain.enums import ActorType
from mediaos.domain.models import AuditEvent, ContentJob
from mediaos.infrastructure.queue_repository import QueueRepository
from mediaos.logging import configure_logging

LOGGER = logging.getLogger(__name__)
HEARTBEAT_PATH = Path("/tmp/mediaos-worker-ready")
HEARTBEAT_SECONDS = 5
WORKER_ID = "mediaos-worker"
WORKER_ACTOR_ID = UUID("00000000-0000-0000-0000-000000000002")
INTERNAL_TASK_TYPES = {
    "HEARTBEAT",
    "INTAKE_ACCEPTED",
    "CHECKLIST_GENERATED",
    "CASE_DEFERRED",
    "INTERNAL_CLASSIFICATION",
}


async def process_one_task() -> bool:
    async with get_session_factory()() as session:
        async with session.begin():
            queue = QueueRepository(session)
            recovered = await queue.recover_stale()
            if recovered:
                LOGGER.warning("recovered %s stale queue claims", recovered)
            task = await queue.claim_next(worker_id=WORKER_ID)
        if task is None:
            return False

        async with session.begin():
            queue = QueueRepository(session)
            job = await session.scalar(select(ContentJob).where(ContentJob.id == task.job_id))
            if task.task_type in INTERNAL_TASK_TYPES:
                await queue.complete(task.id)
                if job is not None:
                    session.add(
                        AuditEvent(
                            tenant_id=job.tenant_id,
                            job_id=job.id,
                            actor_id=WORKER_ACTOR_ID,
                            actor_type=ActorType.WORKER,
                            event_type="QUEUE_TASK_COMPLETED",
                            payload={"task_id": str(task.id), "task_type": task.task_type},
                        )
                    )
                LOGGER.info("task %s completed", task.id)
            else:
                failed = await queue.fail(task.id, error=f"unsupported task type: {task.task_type}")
                if job is not None:
                    session.add(
                        AuditEvent(
                            tenant_id=job.tenant_id,
                            job_id=job.id,
                            actor_id=WORKER_ACTOR_ID,
                            actor_type=ActorType.WORKER,
                            event_type="QUEUE_TASK_FAILED",
                            payload={
                                "task_id": str(task.id),
                                "task_type": task.task_type,
                                "persistent": failed.status.value == "FAILED",
                            },
                        )
                    )
                LOGGER.warning(
                    "task %s failed and was scheduled according to retry policy", task.id
                )
        return True


async def run() -> None:
    configure_logging()
    LOGGER.info("worker started with PostgreSQL SKIP LOCKED queue")
    try:
        while True:
            if await database_ready():
                HEARTBEAT_PATH.touch()
                await process_one_task()
            else:
                HEARTBEAT_PATH.unlink(missing_ok=True)
                LOGGER.error("worker database heartbeat failed")
            await asyncio.sleep(HEARTBEAT_SECONDS)
    finally:
        HEARTBEAT_PATH.unlink(missing_ok=True)
        await close_engine()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        LOGGER.info("worker stopped")


if __name__ == "__main__":
    main()
