"""Phase 0 PostgreSQL queue worker and readiness heartbeat."""

import asyncio
import logging
from pathlib import Path

from mediaos.database import close_engine, database_ready, get_session_factory
from mediaos.infrastructure.queue_repository import QueueRepository
from mediaos.logging import configure_logging

LOGGER = logging.getLogger(__name__)
HEARTBEAT_PATH = Path("/tmp/mediaos-worker-ready")
HEARTBEAT_SECONDS = 5
WORKER_ID = "mediaos-worker"


async def process_one_task() -> bool:
    async with get_session_factory()() as session:
        async with session.begin():
            queue = QueueRepository(session)
            task = await queue.claim_next(worker_id=WORKER_ID)
        if task is None:
            return False

        async with session.begin():
            queue = QueueRepository(session)
            if task.task_type == "HEARTBEAT":
                await queue.complete(task.id)
                LOGGER.info("task %s completed", task.id)
            else:
                await queue.fail(task.id, error=f"unsupported task type: {task.task_type}")
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
