from __future__ import annotations

import asyncio
import sys

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass  # Windows — uvloop not available, stdlib asyncio is used

from src.core.app import Application
from src.core.config import get_settings
from src.core.container import get_container
from src.core.logging_setup import configure_logging, get_logger
from src.secrets.vault import get_vault


async def main() -> None:
    settings = get_settings()
    configure_logging(level=settings.logging.level, fmt=settings.logging.format)
    logger = get_logger(__name__)

    vault = get_vault()
    container = get_container()

    container.register(type(settings), settings)
    container.register(type(vault), vault)

    logger.info("cexvscex.init", env=settings.app.env, debug=settings.app.debug)

    app = Application(container)
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
