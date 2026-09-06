from __future__ import annotations

import logging


def configure_logging(level: str, *, debug_siri_logging: bool = False) -> None:
    effective_level = logging.DEBUG if debug_siri_logging else getattr(
        logging, level.upper(), logging.INFO
    )
    logging.basicConfig(
        level=effective_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
