# XAUBot TradFi

Hệ thống quản lý Bot Trade **XAUUSD** trên **Bybit TradFi (MT5)** — backend FastAPI, worker Windows + MT5, giao diện React.

## Cấu trúc dự án

```
Bot/
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
│   ├── tests/
│   ├── requirements.txt
│   ├── docker-compose.yml
│   └── .env.example
├── frontend/                # React + Vite + Shadcn UI
│   ├── src/pages/           # Dashboard, Positions, History, …
│   └── vite.config.ts       # Dev proxy /api → backend
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

| Method | Path                                   | Mô tả                                                                 |
| ------ | -------------------------------------- | --------------------------------------------------------------------- |
| GET    | `/api/bot/config`                      | Lấy cấu hình tất cả bot                                               |
| POST   | `/api/bot/config`                      | Cập nhật / tạo cấu hình (validate weights)                            |
| GET    | `/api/bot/status`                      | Bot + lệnh mở + lịch sử gần đây + MT5 meta (tick, P&L live)             |
| GET    | `/api/bot/signals/{bot_id}`            | Net signal & breakdown (cần MT5)                                      |
| POST   | `/api/bot/{bot_id}/start`              | Bật bot (RUNNING)                                                     |
| POST   | `/api/bot/{bot_id}/stop`               | Dừng bot (không đóng lệnh)                                            |
| POST   | `/api/bot/stop-all`                    | Khẩn cấp: dừng tất cả bot & đóng vị thế                               |
| GET    | `/api/bot/history`                     | Lịch sử đã đóng — filter, search, phân trang (xem query bên dưới)     |
| POST   | `/api/bot/history/resync-pnl`          | Đồng bộ lại P&L lịch sử từ deal MT5 (khớp Exness)                     |
| GET    | `/api/bot/logs`                        | System logs (`?level=ERROR`, `?limit=200`)                            |
| GET    | `/api/bot/exchanges`                   | Thông tin sàn từ `.env` (không gọi MT5)                               |
| GET    | `/api/bot/exchanges/check`             | Kiểm tra kết nối MT5 thực tế (~8s)                                     |
| POST   | `/api/bot/positions/{id}/close`        | Đóng một lệnh tại giá market                                          |
| POST   | `/api/bot/positions/close-all`         | Đóng tất cả lệnh đang mở tại giá market                               |
| GET    | `/health`                              | Health check                                                          |

### Query `/api/bot/history`

| Param       | Mô tả                                      | Mặc định |
| ----------- | ------------------------------------------ | -------- |
| `days`      | Lọc theo số ngày gần nhất (1–365)          | tất cả   |
| `side`      | `BUY` hoặc `SELL`                          | tất cả   |
| `q`         | Tìm ticket / symbol / close_reason         | —        |
| `page`      | Trang (≥ 1)                                | `1`      |
| `page_size` | Số bản ghi / trang (1–100)                 | `20`     |

Response dạng phân trang:

```json
{
  "items": [...],
  "total": 42,
  "page": 1,
  "page_size": 20,
  "total_pages": 3,
  "total_pnl": 12.34
}
```

## Chạy backend (local)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env
# Tạo DB trước: CREATE DATABASE XAUBOT CHARACTER SET utf8mb4;
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

Swagger UI: [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs)

> **Lưu ý cổng:** Vite dev proxy trỏ tới `:8001` (`frontend/vite.config.ts`). Nếu chạy backend cổng khác, sửa `target` trong file đó hoặc set `VITE_API_URL` trong `frontend/.env`.

### MySQL

- Cài local: thường dùng `localhost:3306` (xem `backend/.env.example`).
- Docker Compose: MySQL expose `localhost:3307` → container `:3306`; cập nhật `DATABASE_URL` tương ứng.

## Chạy worker (Windows + MT5)

```bash
cd backend
.venv\Scripts\activate
# MT5 terminal đã đăng nhập (Exness / Bybit TradFi), chart XAUUSD+
python -m app.worker
```

Worker chỉ xử lý bot có `status = RUNNING`. Bật qua API: `POST /api/bot/2/start`.

Cấu hình MT5 trong `backend/.env`:

| Biến                  | Mô tả                          |
| --------------------- | ------------------------------ |
| `MT5_PATH`            | Đường dẫn `terminal64.exe`     |
| `MT5_LOGIN`           | Login (để trống = terminal hiện tại) |
| `MT5_PASSWORD`        | Password                       |
| `MT5_SERVER`          | Server broker                  |
| `WORKER_TICK_SECONDS` | Chu kỳ tick worker (mặc định 5)|

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

Vite dev proxy `/api` và `/health` → backend `http://127.0.0.1:8001` (cần backend đang chạy).

### Trang UI

| Route           | Mô tả                                                                                      |
| --------------- | ------------------------------------------------------------------------------------------ |
| `/login`        | Đăng nhập admin                                                                            |
| `/`             | **Dashboard** — lệnh mở, lời/lỗ đã đóng, lời hôm nay, biểu đồ P&L; filter **7 / 30 / 90 ngày** (mặc định 7) |
| `/positions`    | Lệnh đang mở, P&L chưa xác thực (MT5 live), đóng từng lệnh / đóng tất cả tại market        |
| `/history`      | Lịch sử đã đóng — filter ngày / chiều lệnh, tìm kiếm, phân trang, đồng bộ P&L từ Exness    |
| `/bot-config`   | Cấu hình bot (gọi API)                                                                     |
| `/exchanges`    | Thông tin sàn MT5; nút kiểm tra kết nối thực tế                                            |
| `/logs`         | Log hệ thống (lọc ERROR)                                                                   |

## Docker (backend + MySQL + frontend)

```bash
cd backend
docker compose up --build
```

- API: [http://localhost:8000](http://localhost:8000)
- UI: [http://localhost:3000](http://localhost:3000) (nginx proxy `/api` → backend)
- MySQL: `localhost:3307` (user `root`, password `123qwe`, DB `XAUBOT`)

## Bước tiếp theo

- Auth thật (JWT / session API)
- Demo account trước khi chạy live
