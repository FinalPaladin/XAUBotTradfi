"""Tests for signal score formula formatting."""



from app.models import BotConfig, BotStatus

from app.trading.signal_format import (

    allowed_nets_label,

    breakdown_weighted_score,

    net_signal_label,

)

from app.trading.types import NetSignal, StrategyResult





def test_breakdown_formula_entry() -> None:

    config = BotConfig(

        id=1,

        name="t",

        status=BotStatus.RUNNING,

        donchian_weight=0.35,

        supertrend_weight=0.30,

        rsi_weight=0.20,

        ema_weight=0.15,

        signal_threshold=0.65,

    )

    results = [

        StrategyResult("donchian", 0.0, {}),

        StrategyResult("supertrend", -1.0, {}),

        StrategyResult("rsi", 1.0, {}),

        StrategyResult("ema21", 0.0, {}),

    ]

    bd = breakdown_weighted_score(config, results, include_rsi=True)

    assert bd["weighted_score"] == -0.1

    assert bd["donchian"] == 0.0

    assert bd["supertrend"] == -1.0

    assert bd["rsi"] == 1.0

    assert bd["ema21"] == 0.0

    assert "= -0.1000" in bd["formula"]





def test_breakdown_formula_with_atr_dampen() -> None:

    config = BotConfig(

        id=1,

        name="t",

        status=BotStatus.RUNNING,

        donchian_weight=0.35,

        supertrend_weight=0.30,

        rsi_weight=0.20,

        ema_weight=0.15,

        signal_threshold=0.65,

    )

    results = [

        StrategyResult("donchian", 1.0, {}),

        StrategyResult("supertrend", 1.0, {}),

        StrategyResult("rsi", 1.0, {}),

        StrategyResult("ema21", 1.0, {}),

    ]

    bd = breakdown_weighted_score(config, results, include_rsi=True, atr_factor=0.5)

    assert bd["weighted_score"] == 0.5

    assert "ATR dampen" in bd["formula"]





def test_net_and_allowed_labels() -> None:

    assert net_signal_label(int(NetSignal.BUY)) == "BUY"

    assert net_signal_label(int(NetSignal.HOLD)) == "HOLD"

    assert allowed_nets_label([-1]) == "SHORT"

    assert allowed_nets_label([1, -1]) == "LONG/SHORT"


