"""Symbol resolution helpers (no MT5 terminal)."""

from app.services.mt5_client import symbol_candidates


def test_xauusd_plus_includes_exness_suffix() -> None:
    candidates = symbol_candidates("XAUUSD+")
    assert "XAUUSDm" in candidates
    assert candidates.index("XAUUSDm") > candidates.index("XAUUSD+")


def test_bare_symbol_variants() -> None:
    candidates = symbol_candidates("XAUUSD")
    assert "XAUUSDm" in candidates
    assert "XAUUSD." in candidates
