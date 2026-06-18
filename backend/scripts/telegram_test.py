"""Send a test Telegram message using .env credentials."""

from __future__ import annotations

import sys

from app.config import get_settings
from app.services.telegram import TelegramHttpClient


def _chat_id_variants(chat_id: str) -> list[str]:
    """Try common Telegram chat_id formats (group vs channel/supergroup)."""
    variants = [chat_id]
    raw = chat_id.lstrip("-")
    supergroup = f"-100{raw}"
    if supergroup not in variants:
        variants.append(supergroup)
    return variants


def main() -> int:
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in .env")
        return 1

    text = (
        "XAUBot Test\n"
        "━━━━━━━━━━━━━━━\n"
        "Ket noi Telegram OK\n"
        "ping tu dev machine"
    )

    last_error: str | None = None
    for cid in _chat_id_variants(settings.telegram_chat_id):
        with TelegramHttpClient(settings.telegram_bot_token, cid) as client:
            result = client.send_message(text)
        if result.ok:
            print(f"Sent OK to chat_id={cid} message_id={result.message_id}")
            if cid != settings.telegram_chat_id:
                print(f"Update .env: TELEGRAM_CHAT_ID={cid}")
            return 0
        last_error = result.error
        print(f"chat_id={cid} -> {result.error}")

    print(f"All attempts failed. Last error: {last_error}")
    print("Fix: add bot to channel as admin, post 1 message, use chat_id -100...")
    return 1


if __name__ == "__main__":
    sys.exit(main())
