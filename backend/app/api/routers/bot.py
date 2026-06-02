"""Bot configuration and control endpoints (placeholders for MT5/Bybit integration)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    BotConfigRead,
    BotConfigUpdate,
    BotStatusResponse,
    MessageResponse,
)

router = APIRouter(prefix="/api/bot", tags=["bot"])


@router.get("/config", response_model=list[BotConfigRead])
def get_bot_config(db: Session = Depends(get_db)) -> list[BotConfigRead]:
    """Lấy cấu hình tất cả bot (hoặc bot mặc định sau khi triển khai service layer)."""
    # TODO: query BotConfig from db; return empty list until seed data exists
    _ = db
    return []


@router.post("/config", response_model=BotConfigRead)
def update_bot_config(
    payload: BotConfigUpdate,
    db: Session = Depends(get_db),
) -> BotConfigRead:
    """Cập nhật cấu hình bot từ UI."""
    # TODO: upsert BotConfig, validate strategy weights sum, persist
    _ = payload, db
    raise HTTPException(
        status_code=501,
        detail="Cập nhật cấu hình chưa triển khai — chờ service layer",
    )


@router.get("/status", response_model=BotStatusResponse)
def get_bot_status(db: Session = Depends(get_db)) -> BotStatusResponse:
    """Xem trạng thái bot, lệnh đang chạy và lịch sử gần đây."""
    # TODO: join bot_config, trade_positions, trade_history
    _ = db
    return BotStatusResponse(
        meta={"placeholder": True, "message": "Chưa kết nối MT5/Bybit"},
    )


@router.post("/stop-all", response_model=MessageResponse)
def stop_all_bots(db: Session = Depends(get_db)) -> MessageResponse:
    """Khẩn cấp: dừng bot và đóng toàn bộ vị thế trên Bybit TradFi."""
    # TODO: set all BotConfig.status = STOPPED; call MT5 close-all; log SystemLog
    _ = db
    return MessageResponse(
        message="stop-all acknowledged (placeholder)",
        detail={"action": "stop_all", "positions_closed": 0},
    )
