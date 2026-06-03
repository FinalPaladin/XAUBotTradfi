"""Trading worker loop — run on Windows alongside MT5 terminal."""

from __future__ import annotations

import logging
import signal
import sys
import time

from app.config import get_settings
from app.database import SessionLocal
from app.models import BotConfig, BotStatus
from app.services.mt5_client import get_mt5_client
from app.services.trading_orchestrator import TradingOrchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("worker")

_running = True


def _handle_stop(_signum, _frame) -> None:
    global _running
    logger.info("Shutdown signal received")
    _running = False


def run_loop() -> None:
    global _running
    settings = get_settings()
    interval = max(1, settings.worker_tick_seconds)

    signal.signal(signal.SIGINT, _handle_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_stop)

    mt5 = get_mt5_client()
    status = mt5.initialize()
    if not status.connected:
        logger.error("MT5 init failed: %s", status.error)
        sys.exit(1)

    logger.info("Worker started (tick=%ss)", interval)

    while _running:
        with SessionLocal() as db:
            bots = (
                db.query(BotConfig)
                .filter(BotConfig.status == BotStatus.RUNNING)
                .all()
            )
            if not bots:
                logger.debug("No RUNNING bots")
            else:
                orchestrator = TradingOrchestrator(db)
                for bot in bots:
                    result = orchestrator.run_tick(bot)
                    logger.info("bot_id=%s result=%s", bot.id, result)

        time.sleep(interval)

    mt5.shutdown()
    logger.info("Worker stopped")


if __name__ == "__main__":
    run_loop()
