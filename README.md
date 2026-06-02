# XAUBot TradFi

Hệ thống quản lý Bot Trade **XAUUSD** trên **Bybit TradFi (MT5)**.

## Cấu trúc dự án

```
XAUBotTradfi/
├── backend/                 # Python / FastAPI
│   ├── app/
│   │   ├── main.py          # FastAPI app + CORS + lifespan
│   │   ├── config.py        # Settings (.env)
│   │   ├── database.py      # Engine, session, init_db
│   │   ├── models.py        # SQLAlchemy ORM (4 bảng)
│   │   ├── schemas.py       # Pydantic DTO cho API/UI
│   │   └── api/routers/
│   │       └── bot.py       # /api/bot/*
│   ├── data/                # SQLite (gitignored *.db)
│   ├── requirements.txt
│   └── .env.example
├── frontend/                # React (sau này)
└── README.md
```

## Database (SQLite + SQLAlchemy)

| Bảng | Mô tả |
|------|--------|
| `bot_config` | Cấu hình bot, TP/SL, trailing, tham số Donchian / SuperTrend / RSI / signal_threshold |
| `trade_positions` | Lệnh đang mở (ticket MT5, side, volume, entry, TP/SL) |
| `trade_history` | Lệnh đã đóng (báo cáo) |
| `system_logs` | Log bot & lỗi API |

## API (placeholder)

| Method | Path | Mô tả |
|--------|------|--------|
| GET | `/api/bot/config` | Lấy cấu hình |
| POST | `/api/bot/config` | Cập nhật cấu hình |
| GET | `/api/bot/status` | Lệnh đang chạy + lịch sử |
| POST | `/api/bot/stop-all` | Dừng bot & đóng hết vị thế |
| GET | `/health` | Health check |

## Chạy backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Swagger UI: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

## Bước tiếp theo (gợi ý)

- Service layer: `services/bot_service.py`, `services/mt5_client.py`
- Seed bot mặc định khi `init_db`
- React UI gọi API qua `CORS_ORIGINS`
