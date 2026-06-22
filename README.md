# XAUBot TradFi

Hệ thống quản lý Bot Trade **XAUUSD** trên **Bybit TradFi / Exness (MT5)** — backend FastAPI, worker Windows + MT5, giao diện React.

Chiến lược chính: **Multi-layer DCA Scalping** (tối đa 4 lớp, spacing 4 giá), tín hiệu Donchian + SuperTrend + RSI + EMA21, hai chế độ **Normal** / **Siêu an toàn**.

## Tài liệu

- [Hướng dẫn chạy local — API, Worker, UI](docs/RUNNING_GUIDE.md)

## Cấu trúc dự án

```
Bot/
├── backend/                 # Python / FastAPI
│   ├── app/
│   │   ├── main.py          # FastAPI app + CORS + lifespan
│   │   ├── config.py        # Settings (.env)
│   │   ├── database.py      # Engine, session, migrations, seed
│   │   ├── seed.py          # Default bot + admin user
│   │   ├── models.py        # SQLAlchemy ORM
│   │   ├── schemas.py       # Pydantic DTO cho API/UI
│   │   ├── core/            # JWT, permissions, security
│   │   ├── trading/         # indicators, strategies, basket DCA, risk
│   │   ├── services/        # mt5_client, bot_service, orchestrator, telegram
│   │   ├── worker/          # trading loop (Windows + MT5, file lock)
│   │   └── api/routers/
│   │       ├── auth.py      # /api/auth/*
│   │       ├── admin.py     # /api/admin/users
│   │       └── bot.py       # /api/bot/*
│   ├── tests/
│   ├── requirements.txt
│   ├── docker-compose.yml
│   └── .env.example
├── frontend/                # React + Vite + Shadcn UI
│   ├── src/pages/           # Dashboard, Positions, History, Bot config, …
│   └── vite.config.ts       # Dev proxy /api → backend :8001
└── README.md
```

## Database (MySQL + SQLAlchemy)

| Bảng              | Mô tả                                                                                 |
| ----------------- | ------------------------------------------------------------------------------------- |
| `users`           | Tài khoản đăng nhập, role, permissions (JWT)                                          |
| `bot_config`      | Cấu hình bot, `trading_mode`, DCA layers, TP/SL, trọng số chiến lược                  |
| `trade_positions` | Lệnh đang mở (ticket MT5, side, volume, layer_index, basket anchor)                  |
| `trade_history`   | Lệnh đã đóng (báo cáo, close_reason)                                                  |
| `system_logs`     | Log bot & lỗi API                                                                     |

## Chiến lược & chế độ giao dịch

### Chế độ Normal / Siêu an toàn (`trading_mode`)

| | **Normal** | **Siêu an toàn** |
| --- | --- | --- |
| DCA tối đa | 4 lớp | 2 lớp |
| Spacing DCA | 4 giá (config) | 5 giá |
| Joint TP basket | ~$1 | ~$0.5 |
| Full-stack loss | 40% balance | 20% balance |
| Entry | Theo signal + H1 trend | Chỉ thuận H1, ngưỡng ≥ 0.80 |

Chọn chế độ trên UI **Cấu hình Bot** → bấm **Lưu**. Chọn **Normal** thủ công đặt `trading_mode_manual = true` — bot không tự chuyển lại Siêu an toàn khi chạm daily guard.

### Daily guard (tự động)

| Sự kiện | Hành vi |
| ------- | ------- |
| Lãi ngày ≥ **$30** | Chuyển **Siêu an toàn** (giữ lệnh mở) |
| Lỗ ngày ≥ **40% balance** | Chuyển **Siêu an toàn** (giữ lệnh mở, **không** đóng hết lệnh) |

### Thoát lệnh basket (DCA)

- **Joint TP** — chốt basket khi đủ lợi nhuận (~$1 Normal).
- **DCA full-stack loss** — đủ 4 lớp (Normal) và tổng lỗ basket ≥ % balance → đóng basket (`DCA_FULL_STACK_LOSS`).
- Volume DCA: `dca_volume_multiplier = 1.0` → mọi lớp **x1** lot (mặc định).

### Tín hiệu M5

- Weighted score: Donchian + SuperTrend + RSI động + EMA21.
- **RSI exhaustion** — chặn LONG/SHORT khi M5 RSI vượt `rsi_overbought` / `rsi_oversold` (mặc định **80 / 20**, chỉnh trên UI).
- H1 xác định trend; M5 timing entry.

### Cảnh báo Telegram

Gửi alert khi mở/đóng lệnh nếu cấu hình `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` trong `.env`.

## API

Tất cả request (trừ login) cần header `X-Secure-Key` (khớp `SECRET_KEY_DYNAMIC`) và `Authorization: Bearer <token>` sau khi đăng nhập.

### Auth

| Method | Path | Mô tả |
| ------ | ---- | ----- |
| POST | `/api/auth/login` | Đăng nhập → JWT |
| GET | `/api/auth/me` | User hiện tại |
| POST | `/api/auth/change-password` | Đổi mật khẩu |

### Bot

| Method | Path | Mô tả |
| ------ | ---- | ----- |
| GET | `/api/bot/config` | Lấy cấu hình tất cả bot |
| POST | `/api/bot/config` | Cập nhật / tạo cấu hình |
| GET | `/api/bot/status` | Bot + lệnh mở + lịch sử gần đây + MT5 meta |
| GET | `/api/bot/signals/{bot_id}` | Net signal & breakdown (cần MT5) |
| POST | `/api/bot/{bot_id}/start` | Bật bot (RUNNING) |
| POST | `/api/bot/{bot_id}/stop` | Dừng bot (không đóng lệnh) |
| POST | `/api/bot/stop-all` | Khẩn cấp: dừng tất cả bot & đóng vị thế |
| GET | `/api/bot/history` | Lịch sử đã đóng — filter, search, phân trang |
| POST | `/api/bot/history/resync-pnl` | Đồng bộ P&L lịch sử từ deal MT5 |
| GET | `/api/bot/logs` | System logs (`?level=ERROR`, `?limit=200`) |
| GET | `/api/bot/exchanges` | Thông tin sàn từ `.env` |
| GET | `/api/bot/exchanges/check` | Kiểm tra kết nối MT5 (~8s) |
| POST | `/api/bot/positions/{id}/close` | Đóng một lệnh tại market |
| POST | `/api/bot/positions/close-all` | Đóng tất cả lệnh đang mở |
| GET | `/health` | Health check |

### Admin (cần permission `admin`)

| Method | Path | Mô tả |
| ------ | ---- | ----- |
| GET | `/api/admin/users` | Danh sách user |
| POST | `/api/admin/users` | Tạo user |
| PUT | `/api/admin/users/{id}` | Cập nhật user |

### Query `/api/bot/history`

| Param | Mô tả | Mặc định |
| ----- | ----- | -------- |
| `days` | Lọc theo số ngày gần nhất (1–365) | tất cả |
| `since` | ISO datetime (ưu tiên hơn `days`) | — |
| `side` | `BUY` hoặc `SELL` | tất cả |
| `pnl` | `WIN` hoặc `LOSS` | tất cả |
| `q` | Tìm ticket / symbol / close_reason | — |
| `page` | Trang (≥ 1) | `1` |
| `page_size` | Số bản ghi / trang (1–100) | `20` |

### Permissions

| Permission | Mô tả |
| ---------- | ----- |
| `read:trades` | Xem dashboard, lịch sử, logs |
| `execute:trades` | Start/stop bot, đóng lệnh |
| `manage:settings` | Sửa cấu hình bot |
| `admin` | Quản lý user |

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

### Biến môi trường chính (`backend/.env`)

| Biến | Mô tả |
| ---- | ----- |
| `DATABASE_URL` | MySQL connection string |
| `MT5_PATH` / `MT5_LOGIN` / `MT5_PASSWORD` / `MT5_SERVER` | Kết nối MT5 |
| `WORKER_TICK_SECONDS` | Chu kỳ tick worker (mặc định `5`) |
| `JWT_SECRET_KEY` | Ký JWT |
| `SECRET_KEY_DYNAMIC` | Header `X-Secure-Key` (khớp frontend) |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Alert Telegram (tùy chọn) |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` / `ADMIN_EMAIL` | Admin bootstrap lần đầu |

### MySQL

- Cài local: thường dùng `localhost:3306` (xem `backend/.env.example`).
- Docker Compose: MySQL expose `localhost:3307` → container `:3306`; cập nhật `DATABASE_URL` tương ứng.

## Chạy worker (Windows + MT5)

```bash
cd backend
.venv\Scripts\activate
# MT5 terminal đã đăng nhập, chart XAUUSD+
python -m app.worker
```

- Chỉ **một** worker được phép chạy (file lock `backend/worker.lock`).
- Worker chỉ xử lý bot có `status = RUNNING`. Bật qua UI `/bot-config` hoặc `POST /api/bot/{id}/start`.

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

Mở [http://127.0.0.1:3000](http://127.0.0.1:3000) — đăng nhập bằng tài khoản admin (mặc định `admin` / `123qwe` từ `.env`, tạo lần đầu khi DB trống).

`frontend/.env`: `VITE_SECRET_KEY_DYNAMIC` phải khớp `SECRET_KEY_DYNAMIC` backend.

### Trang UI

| Route | Mô tả |
| ----- | ----- |
| `/login` | Đăng nhập JWT |
| `/` | **Dashboard** — lệnh mở, P&L, biểu đồ; filter hôm nay / 7 / 30 / 90 ngày |
| `/positions` | Lệnh đang mở, P&L live MT5, đóng lệnh |
| `/history` | Lịch sử đã đóng — filter, tìm kiếm, phân trang, resync P&L |
| `/bot-config` | Cấu hình bot, chế độ Normal / Siêu an toàn, DCA, chiến lược |
| `/exchanges` | Thông tin sàn MT5, kiểm tra kết nối |
| `/logs` | System logs (lọc ERROR) |
| `/admin/users` | Quản lý user (admin) |

## Docker (backend + MySQL + frontend)

```bash
cd backend
docker compose up --build
```

- API: [http://localhost:8000](http://localhost:8000)
- UI: [http://localhost:3000](http://localhost:3000) (nginx proxy `/api` → backend)
- MySQL: `localhost:3307` (user `root`, password `123qwe`, DB `XAUBOT`)

> Docker **không** chạy Worker — Worker cần Windows + MT5 local.

## Ghi chú vận hành

- **Đổi chế độ giao dịch:** chọn Normal / Siêu an toàn trên UI rồi bấm **Lưu** (chỉ click chọn chưa đủ).
- **Worker lock:** nếu gặp `Another worker holds the lock`, chỉ giữ một instance — xem [RUNNING_GUIDE.md](docs/RUNNING_GUIDE.md).
- **Close reason phổ biến:** `BASKET_TP`, `DCA_FULL_STACK_LOSS`, `SCALP_TP`, `POSITION_LOSS_16U` (chỉ khi `max_layers ≤ 1`).
