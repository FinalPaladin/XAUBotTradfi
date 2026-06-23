"""Thin MetaTrader5 wrapper for Bybit TradFi on Windows."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
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

POSITION_NOT_FOUND = "Position not found"

# Common MT5 broker suffixes (Exness → XAUUSDm, some → XAUUSD., etc.)
_SYMBOL_SUFFIXES = ("m", ".", "#", "c", "i", "pro", "_i")


def symbol_candidates(symbol: str) -> list[str]:
    """Ordered alias list when resolving a configured symbol on MT5."""
    bare = symbol.replace("+", "").rstrip(".")
    out: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        if name and name not in seen:
            seen.add(name)
            out.append(name)

    add(symbol)
    add(bare)
    add(f"{bare}+")
    add("XAUUSD+")
    add("XAUUSD")
    for suffix in _SYMBOL_SUFFIXES:
        add(f"{bare}{suffix}")
    return out


@dataclass
class MT5ConnectionStatus:
    connected: bool
    terminal_info: dict[str, Any] | None = None
    account: dict[str, Any] | None = None
    error: str | None = None


def _account_matches(settings: Any, acc: Any) -> bool:
    """True when terminal GUI session already uses the configured account."""
    if acc is None or settings.mt5_login is None:
        return False
    if int(acc.login) != int(settings.mt5_login):
        return False
    if settings.mt5_server and acc.server:
        want = settings.mt5_server.casefold()
        got = str(acc.server).casefold()
        return want in got or got in want
    return True  # login matches; server not configured or not reported yet


@dataclass
class CloseFillResult:
    ok: bool
    error: str | None = None
    fill_price: float | None = None
    net_pnl: float | None = None
    deal_ticket: int | None = None
    entry_price: float | None = None


class MT5Client:
    """Singleton-style MT5 session for worker and API status checks."""

    def __init__(self) -> None:
        self._initialized = False

    def _try_initialize(self, settings: Any, *, quick: bool = False) -> bool:
        if mt5 is None:
            return False

        timeout_ms = int(settings.mt5_connect_timeout_ms)
        # Never pass credentials to initialize() — that spawns/re-auth and often fails
        # while the GUI session is already logged in.
        attempts: list[dict[str, Any]] = [{}]
        if settings.mt5_path and not quick:
            attempts.append({"path": settings.mt5_path})

        for kwargs in attempts:
            mt5.shutdown()
            if mt5.initialize(timeout=timeout_ms, **kwargs):
                return True
        return False

    def initialize(self, *, quick: bool = False) -> MT5ConnectionStatus:
        if mt5 is None:
            return MT5ConnectionStatus(
                connected=False,
                error="MetaTrader5 package not installed",
            )

        settings = get_settings()

        if self._initialized and mt5.terminal_info() is not None:
            return self._status()

        if not self._try_initialize(settings, quick=quick):
            err = mt5.last_error()
            mt5.shutdown()
            self._initialized = False
            msg = f"initialize failed: {err}"
            if err and err[0] == -6:
                msg += (
                    " — Mở MT5, đăng nhập Exness-MT5Trial17, bật "
                    "Tools→Options→Expert Advisors→Allow algorithmic trading "
                    "(và Allow DLL imports), rồi thử lại."
                )
            return MT5ConnectionStatus(connected=False, error=msg)

        acc = mt5.account_info()
        if _account_matches(settings, acc):
            self._initialized = True
            return self._status()
        if acc is not None and settings.mt5_login is not None:
            if int(acc.login) == int(settings.mt5_login):
                self._initialized = True
                return self._status()

        if (
            not quick
            and settings.mt5_login
            and settings.mt5_password
            and settings.mt5_server
        ):
            if not mt5.login(
                login=settings.mt5_login,
                password=settings.mt5_password,
                server=settings.mt5_server,
            ):
                acc = mt5.account_info()
                if acc is not None and int(acc.login) == int(settings.mt5_login):
                    self._initialized = True
                    return self._status()
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
        for alt in symbol_candidates(symbol):
            if mt5.symbol_info(alt) is not None:
                mt5.symbol_select(alt, True)
                return alt
        bare = symbol.replace("+", "").rstrip(".")
        if bare:
            matches = mt5.symbols_get(f"{bare}*")
            if matches:
                for sym in matches:
                    if sym.visible:
                        mt5.symbol_select(sym.name, True)
                        return sym.name
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
        if not self._initialized:
            self.initialize(quick=True)
        resolved = self.resolve_symbol(symbol)
        if not resolved:
            return None
        return mt5.symbol_info_tick(resolved)

    def position_live(self, ticket: int) -> dict[str, float] | None:
        """Giá thị trường và P&L chưa xác thực trực tiếp từ MT5."""
        if mt5 is None:
            return None
        if not self._initialized:
            self.initialize(quick=True)
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return None
        p = positions[0]
        return {
            "price_current": float(p.price_current),
            "profit": float(p.profit),
            "swap": float(p.swap),
        }

    def account_equity(self) -> float:
        if mt5 is None:
            return 0.0
        acc = mt5.account_info()
        return float(acc.equity) if acc else 0.0

    def account_balance(self) -> float:
        if mt5 is None:
            return 0.0
        if not self._initialized:
            self.initialize(quick=True)
        acc = mt5.account_info()
        return float(acc.balance) if acc else 0.0

    def cancel_pending_orders(
        self,
        symbol: str | None = None,
        magic: int | None = None,
    ) -> int:
        """Hủy toàn bộ lệnh chờ (pending) theo symbol/magic."""
        if mt5 is None:
            return 0
        if not self._initialized:
            self.initialize(quick=True)

        resolved = self.resolve_symbol(symbol) if symbol else None
        orders = mt5.orders_get(symbol=resolved) if resolved else mt5.orders_get()
        if orders is None:
            return 0

        cancelled = 0
        for order in orders:
            if magic is not None and order.magic != magic:
                continue
            request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": int(order.ticket),
            }
            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                cancelled += 1
        return cancelled

    def positions_get(self, symbol: str | None = None, magic: int | None = None) -> list:
        if mt5 is None:
            return []
        positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if positions is None:
            return []
        if magic is None:
            return list(positions)
        return [p for p in positions if p.magic == magic]

    def position_is_open(self, ticket: int) -> bool:
        """True when MT5 still reports an open position for this ticket."""
        if mt5 is None:
            return False
        if not self._initialized:
            self.initialize(quick=True)
        positions = mt5.positions_get(ticket=ticket)
        return bool(positions)

    def position_exit_from_history(
        self, ticket: int
    ) -> tuple[float | None, float | None]:
        """Exit price and net P&L from deal history when position is already closed."""
        return self._resolve_close_fill(ticket, None)

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

    def position_entry_price(self, ticket: int) -> float | None:
        """Giá vào thực từ MT5 (price_open) — khớp Exness."""
        if mt5 is None:
            return None
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return None
        return float(positions[0].price_open)

    def _deal_from_ticket(
        self, deal_ticket: int
    ) -> tuple[float | None, float | None]:
        """Giá khớp và P&L từ deal — dùng profit (khớp cột Lãi/Lỗ Exness)."""
        if mt5 is None:
            return None, None
        deals = mt5.history_deals_get(ticket=deal_ticket)
        if not deals:
            return None, None
        d = deals[0]
        return float(d.price), float(d.profit)

    def _resolve_close_fill(
        self, position_ticket: int, deal_ticket: int | None
    ) -> tuple[float | None, float | None]:
        """
        Lấy giá đóng + P&L thực sau khi close — retry vì deal history có độ trễ.
        """
        if mt5 is None:
            return None, None

        if deal_ticket:
            for _ in range(10):
                price, pnl = self._deal_from_ticket(deal_ticket)
                if pnl is not None:
                    return price, pnl
                time.sleep(0.05)

        from datetime import datetime, timedelta

        now = datetime.now()
        deals = mt5.history_deals_get(now - timedelta(minutes=10), now)
        if deals is not None:
            out_deals = [
                d
                for d in deals
                if int(d.position_id) == int(position_ticket)
                and d.entry == mt5.DEAL_ENTRY_OUT
            ]
            if out_deals:
                d = sorted(out_deals, key=lambda x: x.time)[-1]
                return float(d.price), float(d.profit)

        try:
            by_pos = mt5.history_deals_get(position=position_ticket)
            if by_pos:
                out_deals = [d for d in by_pos if d.entry == mt5.DEAL_ENTRY_OUT]
                if out_deals:
                    d = out_deals[-1]
                    return float(d.price), float(d.profit)
        except TypeError:
            pass

        return None, None

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

    def _position_close_send(self, ticket: int, *, tick: Any | None = None) -> CloseFillResult:
        """Gửi lệnh đóng MT5 — không chờ deal history (dùng trong batch close)."""
        if mt5 is None:
            return CloseFillResult(ok=False, error="MetaTrader5 not available")
        if not self._initialized:
            self.initialize(quick=True)

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return CloseFillResult(ok=False, error=POSITION_NOT_FOUND)

        pos = positions[0]
        entry_price = float(pos.price_open)
        if tick is None:
            tick = mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            return CloseFillResult(ok=False, error=str(mt5.last_error()))

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
            return CloseFillResult(ok=False, error=str(mt5.last_error()))
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return CloseFillResult(
                ok=False, error=f"{result.retcode}: {result.comment}"
            )

        deal_ticket = int(result.deal) if result.deal else None
        fill_price = float(result.price) if result.price else price
        return CloseFillResult(
            ok=True,
            fill_price=fill_price,
            deal_ticket=deal_ticket,
            entry_price=entry_price,
        )

    def _finalize_close_result(
        self, ticket: int, sent: CloseFillResult, *, fallback_price: float | None = None
    ) -> CloseFillResult:
        if not sent.ok:
            return sent

        fill_price, net_pnl = self._resolve_close_fill(ticket, sent.deal_ticket)
        if fill_price is None:
            fill_price = sent.fill_price or fallback_price
        return CloseFillResult(
            ok=True,
            fill_price=fill_price,
            net_pnl=net_pnl,
            deal_ticket=sent.deal_ticket,
            entry_price=sent.entry_price,
        )

    def position_close(self, ticket: int) -> CloseFillResult:
        sent = self._position_close_send(ticket)
        if not sent.ok:
            return sent
        return self._finalize_close_result(ticket, sent)

    def positions_close_batch(self, tickets: list[int]) -> dict[int, CloseFillResult]:
        """
        Đóng nhiều position gần như cùng lúc:
        1) Lấy tick một lần / symbol
        2) Gửi toàn bộ order_send liên tiếp (không chờ deal history giữa các lệnh)
        3) Resolve P&L sau một lần
        """
        if not tickets:
            return {}
        if mt5 is None:
            err = CloseFillResult(ok=False, error="MetaTrader5 not available")
            return {ticket: err for ticket in tickets}
        if not self._initialized:
            self.initialize(quick=True)

        tick_cache: dict[str, Any] = {}
        sent_by_ticket: dict[int, CloseFillResult] = {}

        for ticket in tickets:
            positions = mt5.positions_get(ticket=ticket)
            if not positions:
                sent_by_ticket[ticket] = CloseFillResult(
                    ok=False, error=POSITION_NOT_FOUND
                )
                continue

            symbol = positions[0].symbol
            if symbol not in tick_cache:
                tick_cache[symbol] = mt5.symbol_info_tick(symbol)
            sent_by_ticket[ticket] = self._position_close_send(
                ticket, tick=tick_cache[symbol]
            )

        if any(result.ok for result in sent_by_ticket.values()):
            time.sleep(0.08)

        finalized: dict[int, CloseFillResult] = {}
        for ticket in tickets:
            sent = sent_by_ticket.get(ticket)
            if sent is None:
                finalized[ticket] = CloseFillResult(
                    ok=False, error=POSITION_NOT_FOUND
                )
                continue
            if not sent.ok:
                finalized[ticket] = sent
                continue
            finalized[ticket] = self._finalize_close_result(ticket, sent)

        return finalized

    def position_close_legacy(
        self, ticket: int
    ) -> tuple[bool, str | None, float | None]:
        """Backward-compatible wrapper."""
        r = self.position_close(ticket)
        return r.ok, r.error, r.fill_price


_mt5_client: MT5Client | None = None


def get_mt5_client() -> MT5Client:
    global _mt5_client
    if _mt5_client is None:
        _mt5_client = MT5Client()
    return _mt5_client


def reset_mt5_client() -> None:
    """Drop cached client so the next check re-attaches to MT5."""
    global _mt5_client
    if mt5 is not None:
        mt5.shutdown()
    _mt5_client = None


_status_cache: MT5ConnectionStatus | None = None
_status_cache_at: float = 0.0
_STATUS_CACHE_TTL_SEC = 15.0


def _probe_mt5_subprocess(quick: bool, wall_timeout: float) -> MT5ConnectionStatus:
    """Run MT5 probe in a child process so a stuck IPC call cannot block the API."""
    backend_root = Path(__file__).resolve().parent.parent.parent
    script = f"""
import json
from app.services.mt5_client import MT5Client

status = MT5Client().initialize(quick={quick!r})
print(json.dumps({{
    "connected": status.connected,
    "error": status.error,
    "account": status.account,
    "terminal_info": status.terminal_info,
}}))
"""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=backend_root,
            capture_output=True,
            text=True,
            timeout=wall_timeout,
        )
    except subprocess.TimeoutExpired:
        return MT5ConnectionStatus(
            connected=False,
            error=(
                f"MT5 không phản hồi trong {wall_timeout:.0f}s — "
                "mở terminal MT5, đăng nhập Exness, bật algorithmic trading."
            ),
        )

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "MT5 probe failed").strip()
        return MT5ConnectionStatus(connected=False, error=detail[:500])

    try:
        payload = json.loads((proc.stdout or "").strip() or "{}")
    except json.JSONDecodeError:
        return MT5ConnectionStatus(
            connected=False,
            error="MT5 probe returned invalid data",
        )

    return MT5ConnectionStatus(
        connected=bool(payload.get("connected")),
        error=payload.get("error"),
        account=payload.get("account"),
        terminal_info=payload.get("terminal_info"),
    )


def check_mt5_status(*, quick: bool = True, force: bool = False) -> MT5ConnectionStatus:
    """Check MT5 with cache + isolated subprocess timeout."""
    global _status_cache, _status_cache_at
    now = time.monotonic()
    if (
        not force
        and _status_cache is not None
        and now - _status_cache_at < _STATUS_CACHE_TTL_SEC
    ):
        return _status_cache

    settings = get_settings()
    wall_timeout = settings.mt5_connect_timeout_ms / 1000 + 3
    status = _probe_mt5_subprocess(quick=quick, wall_timeout=wall_timeout)

    _status_cache = status
    _status_cache_at = now
    return status
