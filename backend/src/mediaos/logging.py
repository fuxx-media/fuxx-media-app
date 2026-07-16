"""Central logging setup."""

import logging

from mediaos.config import get_settings


def configure_logging() -> None:
    level_name = get_settings().mediaos_log_level.upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )

