"""Weighted multi-strategy signal aggregation."""

from app.models import BotConfig
from app.trading.scoring import compute_strategy_scores
from app.trading.types import AggregatedSignal, NetSignal, OHLCV


def aggregate_signal(df: OHLCV, config: BotConfig) -> AggregatedSignal:
    results = compute_strategy_scores(df, config)

    weighted = (
        config.donchian_weight * results[0].score
        + config.supertrend_weight * results[1].score
        + config.rsi_weight * results[2].score
    )

    threshold = config.signal_threshold
    if weighted >= threshold:
        net = int(NetSignal.BUY)
    elif weighted <= -threshold:
        net = int(NetSignal.SELL)
    else:
        net = int(NetSignal.HOLD)

    return AggregatedSignal(
        strategy_results=results,
        weighted_score=weighted,
        net_signal=net,
    )
