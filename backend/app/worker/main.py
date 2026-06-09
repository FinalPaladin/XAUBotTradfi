"""Trading worker loop — run on Windows alongside MT5 terminal."""

from __future__ import annotations

import atexit
import logging
import os
import signal
import sys
import time

from app.config import BACKEND_ROOT, get_settings
from app.database import SessionLocal
from app.models import BotConfig, BotStatus
from app.services.mt5_client import get_mt5_client
from app.services.trading_orchestrator import TradingOrchestrator
from app.worker.tick_log import format_tick_log

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("worker")

_running = True
_LOCK_FILE = BACKEND_ROOT / "worker.lock"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _acquire_worker_lock() -> None:
    """Refuse to start if another worker process is already running."""
    if _LOCK_FILE.exists():
        try:
            other_pid = int(_LOCK_FILE.read_text(encoding="utf-8").strip())
        except ValueError:
            other_pid = 0
        if _pid_alive(other_pid):
            logger.error(
                "Another worker is already running (pid=%s). Exiting.", other_pid
            )
            sys.exit(1)
        _LOCK_FILE.unlink(missing_ok=True)

    _LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")

    def _release() -> None:
        try:
            if _LOCK_FILE.exists() and _LOCK_FILE.read_text(encoding="utf-8").strip() == str(
                os.getpid()
            ):
                _LOCK_FILE.unlink(missing_ok=True)
        except OSError:
            pass

    atexit.register(_release)


def _handle_stop(_signum, _frame) -> None:
    global _running
    logger.info("Shutdown signal received")
    _running = False


def run_loop() -> None:
    global _running
    _acquire_worker_lock()
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
        try:
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
                        logger.info("\n%s", format_tick_log(result))
        except Exception:
            logger.exception("Worker tick failed — continuing next interval")

        time.sleep(interval)

    mt5.shutdown()
    logger.info("Worker stopped")


if __name__ == "__main__":
    run_loop()
