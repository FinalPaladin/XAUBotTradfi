"""Tests for datetime timezone normalization."""

from datetime import datetime, timezone

from app.trading.datetime_utils import coerce_utc, utc_now


def test_coerce_utc_naive_mysql_utc() -> None:
    naive = datetime(2026, 6, 11, 8, 10, 41)
    result = coerce_utc(naive)
    assert result.tzinfo == timezone.utc
    assert result.hour == 8
    assert result.minute == 10


def test_coerce_utc_aware_passthrough() -> None:
    aware = datetime(2026, 6, 11, 9, 40, 1, tzinfo=timezone.utc)
    result = coerce_utc(aware)
    assert result == aware


def test_utc_now_is_aware() -> None:
    now = utc_now()
    assert now.tzinfo == timezone.utc
