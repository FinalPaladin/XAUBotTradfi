"""Default bot configuration seeded on first startup."""

from sqlalchemy.orm import Session

from app.models import BotConfig, BotStatus


def _default_xauusd_bot() -> BotConfig:
    """Multi-layer DCA Scalping XAUUSD — M5, leverage x50, max 5 layers."""
    return BotConfig(
        name="XAUUSD Primary",
        status=BotStatus.STOPPED,
        symbol="XAUUSD+",
        timeframe="M5",
        bars_lookback=500,
        risk_per_trade_pct=1.0,
        max_open_positions=5,
        magic_number=202501,
        rsi_swing_lookback=5,
        take_profit_pct=0.05,
        stop_loss_pct=0.0,
        trailing_stop_enabled=False,
        trailing_stop_pct=None,
        max_layers=5,
        isolated_leverage=50,
        base_equity_usd=200.0,
        first_layer_notional_usd=6750.0,
        dca_volume_multiplier=1.35,
        layer_spacing_min=5.0,
        layer_spacing_max=7.0,
        basket_tp_min_usd=2.0,
        basket_tp_max_usd=5.0,
        single_tp_min_usd=2.0,
        single_tp_max_usd=3.0,
        single_tp_distance=2.0,
        hard_stop_adverse_distance=9.0,
        max_basket_loss_usd=50.0,
        max_basket_loss_pct=0.0,
        counter_trend_max_layers=5,
        atr_stop_multiplier=2.0,
        basket_time_stop_minutes=60,
        donchian_period=20,
        donchian_weight=0.35,
        supertrend_period=10,
        supertrend_multiplier=3.0,
        supertrend_weight=0.30,
        rsi_period=14,
        rsi_overbought=70.0,
        rsi_oversold=30.0,
        rsi_weight=0.20,
        ema_period=21,
        ema_weight=0.15,
        signal_threshold=0.65,
    )


def seed_if_empty(db: Session) -> bool:
    """Insert default bot config when bot_config has no rows. Returns True if seeded."""
    if db.query(BotConfig).count() > 0:
        return False
    db.add(_default_xauusd_bot())
    return True
