"""Bot configuration and control endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import BotStatus, LogLevel, OrderSide
from app.schemas import (
    AggregatedSignalRead,
    BotConfigRead,
    BotConfigUpdate,
    BotStatusResponse,
    ExchangeConfigRead,
    MessageResponse,
    SystemLogRead,
    TradeHistoryPageRead,
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


@router.get("/history", response_model=TradeHistoryPageRead)
def get_trade_history(
    days: int | None = Query(None, ge=1, le=365),
    since: datetime | None = Query(None),
    side: OrderSide | None = None,
    pnl: str | None = Query(None, pattern="^(WIN|LOSS|win|loss)$"),
    q: str | None = Query(None, max_length=64),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> TradeHistoryPageRead:
    """Lịch sử vị thế đã đóng — filter, phân trang."""
    return BotService(db).list_history_page(
        days=days,
        since=since,
        side=side,
        pnl=pnl,
        search=q,
        page=page,
        page_size=page_size,
    )


@router.get("/logs", response_model=list[SystemLogRead])
def get_system_logs(
    level: LogLevel | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
) -> list[SystemLogRead]:
    """Log hệ thống (mặc định tất cả; UI lọc ERROR)."""
    return BotService(db).list_logs(level=level, limit=min(limit, 1000))


@router.get("/exchanges", response_model=list[ExchangeConfigRead])
def get_exchanges(db: Session = Depends(get_db)) -> list[ExchangeConfigRead]:
    """Thông tin sàn từ .env (phản hồi ngay, không gọi MT5)."""
    return BotService(db).list_exchanges(live=False)


@router.get("/exchanges/check", response_model=list[ExchangeConfigRead])
def check_exchanges(db: Session = Depends(get_db)) -> list[ExchangeConfigRead]:
    """Kiểm tra kết nối MT5 thực tế (timeout ~8s)."""
    return BotService(db).list_exchanges(live=True)


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


@router.post("/history/resync-pnl", response_model=MessageResponse)
def resync_history_pnl(db: Session = Depends(get_db)) -> MessageResponse:
    """Đồng bộ lại P&L lịch sử từ deal MT5 (khớp Exness)."""
    try:
        detail = BotService(db).resync_history_pnl_from_mt5()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return MessageResponse(
        message="History P&L resynced from MT5",
        detail=detail,
    )


@router.post("/positions/close-all", response_model=MessageResponse)
def close_all_positions(db: Session = Depends(get_db)) -> MessageResponse:
    """Đóng tất cả lệnh đang mở tại giá market (bot vẫn RUNNING)."""
    try:
        detail = BotService(db).close_all_open_positions()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return MessageResponse(
        message="All open positions closed at market",
        detail=detail,
    )


@router.post("/positions/{position_id}/close", response_model=MessageResponse)
def close_single_position(
    position_id: int,
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Đóng một lệnh tại giá market."""
    try:
        detail = BotService(db).close_position_by_id(position_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return MessageResponse(
        message="Position closed at market",
        detail=detail,
    )


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
