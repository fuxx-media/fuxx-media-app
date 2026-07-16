"""Phase 0.1 worker heartbeat.

This process proves the shared application/runtime boundary and PostgreSQL
connectivity. PostgreSQL task claiming is intentionally deferred to Phase 0.4.
"""

import asyncio
import logging
from pathlib import Path

from mediaos.database import close_engine, database_ready
from mediaos.logging import configure_logging

LOGGER = logging.getLogger(__name__)
HEARTBEAT_PATH = Path("/tmp/mediaos-worker-ready")
HEARTBEAT_SECONDS = 5


async def run() -> None:
    configure_logging()
    LOGGER.info("worker skeleton started; queue claiming is not implemented in Phase 0.1")
    try:
        while True:
            if await database_ready():
                HEARTBEAT_PATH.touch()
                LOGGER.debug("worker database heartbeat succeeded")
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
        LOGGER.info("worker skeleton stopped")


if __name__ == "__main__":
    main()

