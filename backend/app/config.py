"""Application settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_MYSQL_URL = (
    "mysql+pymysql://root:123qwe@localhost:3306/XAUBOT?charset=utf8mb4"
)


class Settings(BaseSettings):
    """Runtime configuration for FastAPI and database."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "XAUBot TradFi"
    debug: bool = False
    database_url: str = DEFAULT_MYSQL_URL
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # MetaTrader 5 (Windows host — worker runs alongside terminal)
    mt5_path: str | None = None
    mt5_login: int | None = None
    mt5_password: str | None = None
    mt5_server: str | None = None
    worker_tick_seconds: int = 5
    mt5_connect_timeout_ms: int = 5000

    # Telegram trade alerts (optional — worker skips when unset)
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    @field_validator("mt5_login", mode="before")
    @classmethod
    def empty_login(cls, v: object) -> object:
        if v == "" or v is None:
            return None
        return v

    @field_validator(
        "mt5_path",
        "mt5_password",
        "mt5_server",
        "telegram_bot_token",
        "telegram_chat_id",
        mode="before",
    )
    @classmethod
    def empty_optional_str(cls, v: object) -> object:
        if v == "":
            return None
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
