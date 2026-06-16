"""Timezone helpers — mọi timestamp lưu/so sánh theo UTC."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def coerce_utc(dt: datetime) -> datetime:
    """
    Chuẩn hóa datetime về UTC.

    Naive từ MySQL (session time_zone = +00:00) → coi là UTC wall-clock.
    Aware → astimezone UTC.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
