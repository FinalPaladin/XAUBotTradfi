"""HTML message templates for Telegram trade alerts."""

from __future__ import annotations

import html

from app.services.telegram.types import CloseTradeAlert, OpenTradeAlert

BLOCK_DIVIDER = "━━━━━━━━━━━━━━━"

_DIRECTION_ICONS = {
    "LONG": "🟢",
    "SHORT": "🔴",
}

_OUTCOME_ICONS = {
    "WIN": "🏆",
    "LOSS": "🩸",
}


def escape_html(text: str) -> str:
    return html.escape(text, quote=False)


def format_price(value: float | None) -> str:
    if value is None:
        return "—"
    return f"${value:,.2f}"


def format_pnl_amount(value: float) -> str:
    sign = "+" if value >= 0 else "-"
    return f"{sign}${abs(value):,.2f}"


def format_pnl_percent(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}"


def build_open_trade_message(alert: OpenTradeAlert) -> str:
    direction = alert.direction.value
    icon = _DIRECTION_ICONS.get(direction, "📊")
    tp = format_price(alert.tp)
    reason = escape_html(alert.reason.strip())
    symbol = escape_html(alert.symbol.strip())
    ticket_id = escape_html(alert.ticket_id.strip())

    return (
        f"{icon} <b>{direction}</b> {symbol}\n"
        f"{BLOCK_DIVIDER}\n"
        f"📍 Entry: <b>{format_price(alert.entry)}</b>\n"
        f"🆔 ID lệnh: <b>{ticket_id}</b>\n"
        f"🎯 TP: <b>{tp}</b>\n"
        f"{BLOCK_DIVIDER}\n"
        f"📝 <b>Phân tích / Lý do:</b>\n"
        f"{reason}"
    )


def build_close_trade_message(alert: CloseTradeAlert) -> str:
    direction = alert.direction.value
    outcome = alert.outcome.value
    icon = _OUTCOME_ICONS.get(outcome, "📊")
    symbol = escape_html(alert.symbol.strip())
    reason = escape_html(alert.reason.strip())
    pnl_amount = format_pnl_amount(alert.pnl_amount)
    pnl_pct = format_pnl_percent(alert.pnl_percent)

    ticket_id = escape_html(alert.ticket_id.strip())
    balance_line = ""
    if alert.account_balance is not None:
        balance_line = (
            f"💵 Số dư TK: <b>{format_price(alert.account_balance)}</b>\n"
        )

    return (
        f"{icon} <b>CLOSE</b> {symbol} - <b>{direction}</b>\n"
        f"{BLOCK_DIVIDER}\n"
        f"💰 PnL: <b>{pnl_amount}</b> ({pnl_pct}%)\n"
        f"📍 Entry: <b>{format_price(alert.entry)}</b>\n"
        f"🏁 Close Price: <b>{format_price(alert.close_price)}</b>\n"
        f"🆔 ID lệnh: <b>{ticket_id}</b>\n"
        f"{balance_line}"
        f"{BLOCK_DIVIDER}\n"
        f"🛑 <b>Lý do đóng:</b>\n"
        f"{reason}"
    )
