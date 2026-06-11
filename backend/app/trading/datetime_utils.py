"""Timezone helpers — mọi timestamp lưu/so sánh theo UTC."""

from __future__ import annotations

from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore[misc, assignment]

# MySQL naive timestamps trước đây lưu theo giờ VN (session local)
_LEGACY_NAIVE_TZ = "Asia/Ho_Chi_Minh"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def coerce_utc(dt: datetime) -> datetime:
    """
    Chuẩn hóa datetime về UTC.

    Naive từ MySQL legacy → coi là Asia/Ho_Chi_Minh rồi chuyển UTC.
    Aware → astimezone UTC.
    """
    if dt.tzinfo is None:
        if ZoneInfo is not None:
            local = ZoneInfo(_LEGACY_NAIVE_TZ)
            return dt.replace(tzinfo=local).astimezone(timezone.utc)
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
