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
├── frontend/                # React + Shadcn UI
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
| GET    | `/api/bot/history`          | Lịch sử vị thế đã đóng                     |
| GET    | `/api/bot/logs`             | System logs (`?level=ERROR`)               |
| GET    | `/api/bot/exchanges`        | Thông tin sàn MT5 / Bybit TradFi           |
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

## Chạy frontend (React + Shadcn UI)

```bash
cd frontend
npm install
npm run dev
```

Mở [http://127.0.0.1:3000](http://127.0.0.1:3000) — đăng nhập: `admin` / `123qwe` (hardcode, chưa gọi API auth).

Vite dev proxy `/api` → backend `:8000` (cần backend đang chạy).

### Trang UI

| Route           | Mô tả                                      |
| --------------- | ------------------------------------------ |
| `/login`        | Đăng nhập admin                            |
| `/`             | Dashboard (lệnh mở, lời/lỗ, P&L 30 ngày)   |
| `/positions`    | Lệnh hiện tại + P&L chưa xác thực          |
| `/history`      | Lịch sử vị thế đã đóng                     |
| `/bot-config`   | Cấu hình bot (gọi API)                     |
| `/exchanges`    | MT5 / BybitTradFi-Real                     |
| `/logs`         | Log lỗi hệ thống                           |

## Docker (backend + MySQL + frontend)

```bash
cd backend
docker compose up --build
```

- API: [http://localhost:8000](http://localhost:8000)
- UI: [http://localhost:3000](http://localhost:3000) (nginx proxy `/api` → backend)

## Bước tiếp theo

- Auth thật (JWT / session API)
- Demo account trước khi chạy live
