"""Persist system logs."""

from sqlalchemy.orm import Session

from app.models import LogLevel, SystemLog


def log_message(
    db: Session,
    message: str,
    *,
    bot_id: int | None = None,
    level: LogLevel = LogLevel.INFO,
    source: str = "bot",
) -> None:
    db.add(
        SystemLog(
            bot_id=bot_id,
            level=level,
            source=source,
            message=message,
        )
    )
