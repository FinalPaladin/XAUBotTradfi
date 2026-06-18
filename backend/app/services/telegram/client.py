"""HTTP client for Telegram Bot API."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)

DEFAULT_PARSE_MODE = "HTML"
TELEGRAM_API_BASE = "https://api.telegram.org"


@dataclass(frozen=True, slots=True)
class TelegramSendResult:
    ok: bool
    message_id: int | None = None
    error: str | None = None


@runtime_checkable
class TelegramNotifier(Protocol):
    """Contract for sending Telegram notifications (swap for mocks in tests)."""

    def send_message(
        self,
        text: str,
        *,
        chat_id: str | None = None,
        parse_mode: str = DEFAULT_PARSE_MODE,
    ) -> TelegramSendResult: ...

    def send_photo(
        self,
        photo: bytes | Path | str | BinaryIO,
        *,
        caption: str = "",
        chat_id: str | None = None,
        parse_mode: str = DEFAULT_PARSE_MODE,
    ) -> TelegramSendResult: ...


class NoOpTelegramNotifier:
    """Disabled notifier when Telegram is not configured."""

    def send_message(
        self,
        text: str,
        *,
        chat_id: str | None = None,
        parse_mode: str = DEFAULT_PARSE_MODE,
    ) -> TelegramSendResult:
        logger.debug("Telegram disabled — skipped send_message (%d chars)", len(text))
        return TelegramSendResult(ok=False, error="telegram_not_configured")

    def send_photo(
        self,
        photo: bytes | Path | str | BinaryIO,
        *,
        caption: str = "",
        chat_id: str | None = None,
        parse_mode: str = DEFAULT_PARSE_MODE,
    ) -> TelegramSendResult:
        logger.debug("Telegram disabled — skipped send_photo")
        return TelegramSendResult(ok=False, error="telegram_not_configured")


class TelegramHttpClient:
    """Sync HTTP client wrapping Telegram sendMessage / sendPhoto."""

    def __init__(
        self,
        bot_token: str,
        default_chat_id: str,
        *,
        timeout: float = 15.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._token = bot_token
        self._default_chat_id = default_chat_id
        self._timeout = timeout
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=f"{TELEGRAM_API_BASE}/bot{bot_token}",
            timeout=timeout,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> TelegramHttpClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _resolve_chat_id(self, chat_id: str | None) -> str:
        return chat_id or self._default_chat_id

    def _post(self, method: str, payload: dict) -> TelegramSendResult:
        try:
            response = self._client.post(f"/{method}", json=payload)
            data = response.json()
        except httpx.HTTPError as exc:
            logger.warning("Telegram %s HTTP error: %s", method, exc)
            return TelegramSendResult(ok=False, error=str(exc))
        except ValueError as exc:
            logger.warning("Telegram %s invalid JSON: %s", method, exc)
            return TelegramSendResult(ok=False, error="invalid_json_response")

        if not data.get("ok"):
            description = data.get("description", "unknown_error")
            logger.warning("Telegram %s API error: %s", method, description)
            return TelegramSendResult(ok=False, error=description)

        result = data.get("result") or {}
        message_id = result.get("message_id")
        return TelegramSendResult(ok=True, message_id=message_id)

    def send_message(
        self,
        text: str,
        *,
        chat_id: str | None = None,
        parse_mode: str = DEFAULT_PARSE_MODE,
    ) -> TelegramSendResult:
        payload: dict = {
            "chat_id": self._resolve_chat_id(chat_id),
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        return self._post("sendMessage", payload)

    def send_photo(
        self,
        photo: bytes | Path | str | BinaryIO,
        *,
        caption: str = "",
        chat_id: str | None = None,
        parse_mode: str = DEFAULT_PARSE_MODE,
    ) -> TelegramSendResult:
        resolved_chat = self._resolve_chat_id(chat_id)
        data = {
            "chat_id": resolved_chat,
            "parse_mode": parse_mode,
            "disable_notification": "false",
        }
        if caption:
            data["caption"] = caption

        files: dict
        if isinstance(photo, (bytes, bytearray)):
            files = {"photo": ("chart.png", photo, "image/png")}
        elif isinstance(photo, Path):
            files = {"photo": (photo.name, photo.read_bytes(), "image/png")}
        elif isinstance(photo, str):
            path = Path(photo)
            files = {"photo": (path.name, path.read_bytes(), "image/png")}
        else:
            files = {"photo": ("chart.png", photo, "image/png")}

        try:
            response = self._client.post("/sendPhoto", data=data, files=files)
            body = response.json()
        except httpx.HTTPError as exc:
            logger.warning("Telegram sendPhoto HTTP error: %s", exc)
            return TelegramSendResult(ok=False, error=str(exc))
        except ValueError as exc:
            logger.warning("Telegram sendPhoto invalid JSON: %s", exc)
            return TelegramSendResult(ok=False, error="invalid_json_response")

        if not body.get("ok"):
            description = body.get("description", "unknown_error")
            logger.warning("Telegram sendPhoto API error: %s", description)
            return TelegramSendResult(ok=False, error=description)

        result = body.get("result") or {}
        return TelegramSendResult(ok=True, message_id=result.get("message_id"))
