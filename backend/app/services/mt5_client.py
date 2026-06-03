"""Thin MetaTrader5 wrapper for Bybit TradFi on Windows."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None  # type: ignore[assignment]


TIMEFRAME_MAP: dict[str, int] = {}


def _build_timeframe_map() -> dict[str, int]:
    if mt5 is None:
        return {
            "M1": 1,
            "M5": 5,
            "M15": 15,
            "M30": 30,
            "H1": 60,
            "H4": 240,
            "D1": 1440,
        }
    return {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }


TIMEFRAME_MAP = _build_timeframe_map()


@dataclass
class MT5ConnectionStatus:
    connected: bool
    terminal_info: dict[str, Any] | None = None
    account: dict[str, Any] | None = None
    error: str | None = None


class MT5Client:
    """Singleton-style MT5 session for worker and API status checks."""

    def __init__(self) -> None:
        self._initialized = False

    def initialize(self) -> MT5ConnectionStatus:
        if mt5 is None:
            return MT5ConnectionStatus(
                connected=False,
                error="MetaTrader5 package not installed",
            )

        settings = get_settings()
        kwargs: dict[str, Any] = {}
        if settings.mt5_path:
            kwargs["path"] = settings.mt5_path

        if self._initialized and mt5.terminal_info() is not None:
            return self._status()

        if not mt5.initialize(**kwargs):
            err = mt5.last_error()
            return MT5ConnectionStatus(
                connected=False,
                error=f"initialize failed: {err}",
            )

        if settings.mt5_login and settings.mt5_password and settings.mt5_server:
            if not mt5.login(
                login=settings.mt5_login,
                password=settings.mt5_password,
                server=settings.mt5_server,
            ):
                err = mt5.last_error()
                return MT5ConnectionStatus(
                    connected=False,
                    error=f"login failed: {err}",
                )

        self._initialized = True
        return self._status()

    def _status(self) -> MT5ConnectionStatus:
        if mt5 is None:
            return MT5ConnectionStatus(connected=False, error="no mt5")
        term = mt5.terminal_info()
        acc = mt5.account_info()
        if term is None:
            return MT5ConnectionStatus(
                connected=False,
                error=str(mt5.last_error()),
            )
        account_dict = None
        if acc is not None:
            account_dict = {
                "login": acc.login,
                "balance": acc.balance,
                "equity": acc.equity,
                "margin": acc.margin,
                "server": acc.server,
            }
        return MT5ConnectionStatus(
            connected=True,
            terminal_info={"name": term.name, "company": term.company},
            account=account_dict,
        )

    def shutdown(self) -> None:
        if mt5 and self._initialized:
            mt5.shutdown()
            self._initialized = False

    def resolve_symbol(self, symbol: str) -> str | None:
        if mt5 is None:
            return symbol
        if mt5.symbol_info(symbol) is not None:
            mt5.symbol_select(symbol, True)
            return symbol
        for alt in (symbol.replace("+", ""), f"{symbol}+", "XAUUSD+", "XAUUSD"):
            if mt5.symbol_info(alt) is not None:
                mt5.symbol_select(alt, True)
                return alt
        return None

    def copy_rates(self, symbol: str, timeframe: str, count: int) -> Any:
        if mt5 is None:
            return None
        tf = TIMEFRAME_MAP.get(timeframe.upper())
        if tf is None:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        resolved = self.resolve_symbol(symbol)
        if not resolved:
            return None
        return mt5.copy_rates_from_pos(resolved, tf, 0, count)

    def symbol_info(self, symbol: str) -> Any:
        if mt5 is None:
            return None
        resolved = self.resolve_symbol(symbol)
        if not resolved:
            return None
        return mt5.symbol_info(resolved)

    def tick(self, symbol: str) -> Any:
        if mt5 is None:
            return None
        resolved = self.resolve_symbol(symbol)
        if not resolved:
            return None
        return mt5.symbol_info_tick(resolved)

    def account_equity(self) -> float:
        if mt5 is None:
            return 0.0
        acc = mt5.account_info()
        return float(acc.equity) if acc else 0.0

    def positions_get(self, symbol: str | None = None, magic: int | None = None) -> list:
        if mt5 is None:
            return []
        positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if positions is None:
            return []
        if magic is None:
            return list(positions)
        return [p for p in positions if p.magic == magic]

    def order_send_market(
        self,
        symbol: str,
        side: str,
        volume: float,
        sl: float,
        tp: float,
        magic: int,
        comment: str,
    ) -> tuple[bool, str | None, int | None]:
        if mt5 is None:
            return False, "MetaTrader5 not available", None

        resolved = self.resolve_symbol(symbol)
        if not resolved:
            return False, f"Symbol not found: {symbol}", None

        info = mt5.symbol_info(resolved)
        tick = mt5.symbol_info_tick(resolved)
        if info is None or tick is None:
            return False, str(mt5.last_error()), None

        volume = max(info.volume_min, min(info.volume_max, volume))
        volume = round(volume / info.volume_step) * info.volume_step

        if side.upper() == "BUY":
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": resolved,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None:
            return False, str(mt5.last_error()), None
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return False, f"{result.retcode}: {result.comment}", None
        return True, None, result.order

    def position_modify(self, ticket: int, sl: float, tp: float) -> tuple[bool, str | None]:
        if mt5 is None:
            return False, "MetaTrader5 not available"
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "sl": sl,
            "tp": tp,
        }
        result = mt5.order_send(request)
        if result is None:
            return False, str(mt5.last_error())
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return False, f"{result.retcode}: {result.comment}"
        return True, None

    def position_close(self, ticket: int) -> tuple[bool, str | None, float | None]:
        if mt5 is None:
            return False, "MetaTrader5 not available", None
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return False, "Position not found", None
        pos = positions[0]
        tick = mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            return False, str(mt5.last_error()), None

        if pos.type == mt5.POSITION_TYPE_BUY:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        else:
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": order_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": pos.magic,
            "comment": "XAUBot close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None:
            return False, str(mt5.last_error()), None
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return False, f"{result.retcode}: {result.comment}", None
        return True, None, price


_mt5_client: MT5Client | None = None


def get_mt5_client() -> MT5Client:
    global _mt5_client
    if _mt5_client is None:
        _mt5_client = MT5Client()
    return _mt5_client
