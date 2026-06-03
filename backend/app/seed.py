"""Default bot configuration seeded on first startup."""

from sqlalchemy.orm import Session

from app.models import BotConfig, BotStatus


def _default_xauusd_bot() -> BotConfig:
    """Conservative XAUUSD TradFi defaults: trend + momentum blend, weights sum to 1."""
    return BotConfig(
        name="XAUUSD Primary",
        status=BotStatus.STOPPED,
        symbol="XAUUSD+",
        timeframe="M15",
        bars_lookback=500,
        risk_per_trade_pct=1.0,
        max_open_positions=1,
        magic_number=202501,
        rsi_swing_lookback=5,
        take_profit_pct=1.2,
        stop_loss_pct=0.6,
        trailing_stop_enabled=True,
        trailing_stop_pct=0.4,
        donchian_period=20,
        donchian_weight=0.35,
        supertrend_period=10,
        supertrend_multiplier=3.0,
        supertrend_weight=0.35,
        rsi_period=14,
        rsi_overbought=70.0,
        rsi_oversold=30.0,
        rsi_weight=0.30,
        signal_threshold=0.65,
    )


def seed_if_empty(db: Session) -> bool:
    """Insert default bot config when bot_config has no rows. Returns True if seeded."""
    if db.query(BotConfig).count() > 0:
        return False
    db.add(_default_xauusd_bot())
    return True
