# XAUBot TradFi

Hệ thống quản lý Bot Trade **XAUUSD** trên **Bybit TradFi (MT5)**.

## Cấu trúc dự án

```
XAUBotTradfi/
├── backend/                 # Python / FastAPI
│   ├── app/
│   │   ├── main.py          # FastAPI app + CORS + lifespan
│   │   ├── config.py        # Settings (.env)
│   │   ├── database.py      # Engine, session, init_db + seed
│   │   ├── seed.py          # Default bot_config on first run
│   │   ├── models.py        # SQLAlchemy ORM (4 bảng)
│   │   ├── schemas.py       # Pydantic DTO cho API/UI
│   │   ├── trading/         # indicators, strategies, risk, execution
│   │   ├── services/        # mt5_client, bot_service, orchestrator
│   │   ├── worker/          # trading loop (Windows + MT5)
│   │   └── api/routers/
│   │       └── bot.py       # /api/bot/*
│   ├── requirements.txt
│   └── .env.example
├── frontend/                # React (sau này)
└── README.md
```

## Database (MySQL + SQLAlchemy)

| Bảng              | Mô tả                                                                                 |
| ----------------- | ------------------------------------------------------------------------------------- |
| `bot_config`      | Cấu hình bot, TP/SL, trailing, tham số Donchian / SuperTrend / RSI / signal_threshold |
| `trade_positions` | Lệnh đang mở (ticket MT5, side, volume, entry, TP/SL)                                 |
| `trade_history`   | Lệnh đã đóng (báo cáo)                                                                |
| `system_logs`     | Log bot & lỗi API                                                                     |

## API

| Method | Path                        | Mô tả                                      |
| ------ | --------------------------- | ------------------------------------------ |
| GET    | `/api/bot/config`           | Lấy cấu hình                               |
| POST   | `/api/bot/config`           | Cập nhật / tạo cấu hình (validate weights) |
| GET    | `/api/bot/status`           | Bot + lệnh mở + lịch sử + MT5 meta         |
| GET    | `/api/bot/signals/{bot_id}` | Net signal & breakdown (cần MT5)           |
| POST   | `/api/bot/{bot_id}/start`   | Bật bot (RUNNING)                          |
| POST   | `/api/bot/{bot_id}/stop`    | Dừng bot (không đóng lệnh)                 |
| POST   | `/api/bot/stop-all`         | Dừng tất cả & đóng vị thế                  |
| GET    | `/health`                   | Health check                               |

## Chạy backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env
# Tạo DB trước: CREATE DATABASE XAUBOT CHARACTER SET utf8mb4;
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Swagger UI: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

## Chạy worker (Windows + MT5)

```bash
cd backend
.venv\Scripts\activate
# MT5 terminal đã đăng nhập Bybit TradFi, chart XAUUSD+
python -m app.worker
```

Worker chỉ xử lý bot có `status = RUNNING`. Bật qua API: `POST /api/bot/1/start`.

## Test (không cần MT5)

```bash
cd backend
pip install pytest
pytest tests/ -q
```

## Bước tiếp theo

- React UI gọi API qua `CORS_ORIGINS`
- Demo account trước khi chạy live
