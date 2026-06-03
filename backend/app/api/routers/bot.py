"""Bot configuration and control endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import BotStatus
from app.schemas import (
    AggregatedSignalRead,
    BotConfigRead,
    BotConfigUpdate,
    BotStatusResponse,
    MessageResponse,
)
from app.services.bot_service import BotService

router = APIRouter(prefix="/api/bot", tags=["bot"])


@router.get("/config", response_model=list[BotConfigRead])
def get_bot_config(db: Session = Depends(get_db)) -> list[BotConfigRead]:
    """Lấy cấu hình tất cả bot."""
    return BotService(db).list_configs()


@router.post("/config", response_model=BotConfigRead)
def update_bot_config(
    payload: BotConfigUpdate,
    db: Session = Depends(get_db),
) -> BotConfigRead:
    """Cập nhật hoặc tạo cấu hình bot từ UI."""
    try:
        return BotService(db).update_config(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/status", response_model=BotStatusResponse)
def get_bot_status(db: Session = Depends(get_db)) -> BotStatusResponse:
    """Xem trạng thái bot, lệnh đang chạy và lịch sử gần đây."""
    service = BotService(db)
    bots, positions, history, meta = service.get_dashboard()
    return BotStatusResponse(
        bots=bots,
        open_positions=positions,
        recent_history=history,
        meta=meta,
    )


@router.get("/signals/{bot_id}", response_model=AggregatedSignalRead)
def get_bot_signals(
    bot_id: int,
    db: Session = Depends(get_db),
) -> AggregatedSignalRead:
    """Debug: weighted scores và net signal hiện tại."""
    try:
        return BotService(db).compute_signals(bot_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/{bot_id}/start", response_model=BotConfigRead)
def start_bot(bot_id: int, db: Session = Depends(get_db)) -> BotConfigRead:
    """Bật bot (worker sẽ xử lý khi status=RUNNING)."""
    try:
        return BotService(db).set_status(bot_id, BotStatus.RUNNING)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{bot_id}/stop", response_model=BotConfigRead)
def stop_bot(bot_id: int, db: Session = Depends(get_db)) -> BotConfigRead:
    """Dừng bot (không đóng lệnh — dùng stop-all để đóng)."""
    try:
        return BotService(db).set_status(bot_id, BotStatus.STOPPED)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/stop-all", response_model=MessageResponse)
def stop_all_bots(db: Session = Depends(get_db)) -> MessageResponse:
    """Khẩn cấp: dừng bot và đóng toàn bộ vị thế trên Bybit TradFi."""
    detail = BotService(db).stop_all()
    return MessageResponse(
        message="All bots stopped and positions closed",
        detail=detail,
    )
