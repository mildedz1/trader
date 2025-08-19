import asyncio
import signal

from app.config.settings import settings
from app.logging import configure_logging, logger
from app.admin_handlers.bot import run_bot


def _install_uvloop_if_available() -> None:
    try:
        import uvloop  # type: ignore

        uvloop.install()
    except Exception:
        pass


async def main() -> None:
    configure_logging(env=settings.app_env)
    logger.info("app.start", env=settings.app_env)

    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    await run_bot(stop_event)
    logger.info("app.stop")


if __name__ == "__main__":
    _install_uvloop_if_available()
    asyncio.run(main())
