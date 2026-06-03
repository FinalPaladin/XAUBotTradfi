"""OHLCV market data from MT5."""

from __future__ import annotations

import pandas as pd

from app.models import BotConfig
from app.services.mt5_client import get_mt5_client


def rates_to_dataframe(rates) -> pd.DataFrame:
    if rates is None or len(rates) == 0:
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


class MarketDataProvider:
    def __init__(self, client=None) -> None:
        self._client = client or get_mt5_client()

    def fetch(self, config: BotConfig) -> pd.DataFrame:
        status = self._client.initialize()
        if not status.connected:
            raise RuntimeError(status.error or "MT5 not connected")

        rates = self._client.copy_rates(
            config.symbol,
            config.timeframe,
            config.bars_lookback,
        )
        df = rates_to_dataframe(rates)
        if df.empty:
            raise RuntimeError(f"No rates for {config.symbol} {config.timeframe}")
        return df

    def current_price(self, symbol: str) -> float:
        tick = self._client.tick(symbol)
        if tick is None:
            raise RuntimeError(f"No tick for {symbol}")
        return (tick.bid + tick.ask) / 2.0
