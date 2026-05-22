"""
Livermore AI worker oficial.

Este proceso es el unico que debe conectar Discord y correr el scanner.
El web service (`main.py`) queda reservado para dashboard/API.
"""
import asyncio
import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

load_dotenv()

from core.runtime import require_cloud_or_exit  # noqa: E402

require_cloud_or_exit("worker.py")

from bot.discord_bot import create_bot, run_bot  # noqa: E402
from core.models import Base, engine  # noqa: E402
from core.scanner import LivermoreScanner  # noqa: E402

logger = logging.getLogger("livermore.worker")


async def _initialize_runtime_data() -> None:
    """Crea tablas y reutiliza las migraciones livianas del web app."""
    try:
        from main import _ensure_schema, _purge_contaminated_alerts

        _ensure_schema()
        Base.metadata.create_all(bind=engine)
        _purge_contaminated_alerts()
    except Exception as exc:
        logger.warning(f"Inicializacion DB del worker fallo (no fatal): {exc}")


async def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    await _initialize_runtime_data()

    bot = create_bot()
    scanner = LivermoreScanner(discord_bot=bot)

    scheduler = AsyncIOScheduler(timezone="America/New_York")
    scheduler.add_job(
        scanner.run_scan,
        "cron",
        day_of_week="mon-fri",
        hour="8-19",
        minute="*/5",
        id="livermore_scanner",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Worker iniciado: Discord + scanner cada 5min en market hours")

    bot_task = asyncio.create_task(run_bot(bot))
    try:
        await bot_task
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())
