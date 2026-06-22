"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import admin, auth, bot
from app.config import get_settings
from app.database import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        description="Quản lý Bot Trade XAUUSD — Bybit TradFi (MT5)",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(auth.router)
    application.include_router(admin.router)
    application.include_router(bot.router)
    return application


app = create_app()


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
