# XAUBot TradFi

Hệ thống quản lý Bot Trade **XAUUSD** trên **Bybit TradFi / Exness (MT5)** — backend FastAPI, worker Windows + MT5, giao diện React.

Chiến lược chính: **Multi-layer DCA Scalping** (3 lớp core gồng chung + DCA vệ tinh không giới hạn), tín hiệu Donchian + SuperTrend + RSI Midline + EMA21 trên khung **H1/M5**, hai chế độ **Normal** / **Siêu an toàn**.

## Tài liệu

| Tài liệu | Mô tả |
| -------- | ----- |
| [Hướng dẫn chạy local](docs/RUNNING_GUIDE.md) | Khởi động API, Worker, UI trên Windows |
| [Technical Overview](docs/TECHNICAL_OVERVIEW.md) | Kiến trúc, worker pipeline, signal engine, DCA basket |
| [Technical Specification](docs/TECHNICAL_SPECIFICATION.md) | Chi tiết chiến lược, scoring, risk, file map |
| [Architect Guide](ARCHITECT_GUIDE.md) | Bản spec dành cho custom / optimize / thêm chiến lược |

## Tech stack

| Thành phần | Công nghệ |
| ---------- | --------- |
| Backend API | Python 3.11+, FastAPI, SQLAlchemy, Pydantic |
| Worker | Windows + MetaTrader 5 (`MetaTrader5` package) |
| Database | MySQL 8 |
| Frontend | React 19, Vite 7, Tailwind CSS 4, Shadcn UI |
| Auth | JWT + header `X-Secure-Key` (rotate 30s) |
| Alert | Telegram Bot API (tùy chọn) |

## Cấu trúc dự án

```
BOT_XAU/
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
├── docs/
└── README.md
```

## Kiến trúc vận hành

Hệ thống gồm **3 process** độc lập, chia sẻ trạng thái qua **MySQL**:

| Process | Entry point | Cổng (local) | Vai trò |
| ------- | ----------- | ------------ | ------- |
| **API** | `uvicorn app.main:app --port 8001` | `8001` | REST API cho UI; CRUD config; start/stop bot |
| **Worker** | `python -m app.worker` | — | Poll DB, thực thi pipeline giao dịch qua MT5 |
| **UI** | `npm run dev` | `3000` | Dashboard, config, positions, history, logs |

> Worker **bắt buộc chạy trên Windows** với MT5 terminal đã đăng nhập. API/UI có thể chạy Docker hoặc local.

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
| Core gồng chung | 3 lớp đầu (joint TP) | 2 lớp |
| DCA vệ tinh | Không giới hạn (spacing ≥ 5 giá) | Không thêm DCA |
| Spacing DCA | 5 giá (config `layer_spacing_min`) | 5 giá |
| Joint TP basket | ~$1 | ~$0.5 |
| Full-stack loss | 40% balance | 20% balance |
| Entry | Theo signal + H1 trend | Chỉ thuận H1, ngưỡng ≥ 0.80 |

Chọn chế độ trên UI **Cấu hình Bot** → bấm **Lưu**. Chọn **Normal** thủ công đặt `trading_mode_manual = true` — bot không tự chuyển lại Siêu an toàn khi chạm daily guard.

### Daily guard (tự động)

| Sự kiện | Hành vi |
| ------- | ------- |
| Lãi ngày ≥ **$30** | Chuyển **Siêu an toàn** (giữ lệnh mở) |
| Lỗ ngày ≥ **40% balance** | Chuyển **Siêu an toàn** (giữ lệnh mở, **không** đóng hết lệnh) |

### Position loss guard

Khi **một lệnh đơn** lỗ ≥ **$16** floating P&L → đóng toàn bộ vị thế và chuyển **Siêu an toàn** (`POSITION_LOSS_16U`).

### Thoát lệnh basket (DCA)

- **Core basket TP** — chốt 3 lớp core khi đủ lợi nhuận (~$1 Normal).
- **Satellite layer TP** — chốt riêng từng lớp DCA vệ tinh khi có lời.
- **DCA full-stack loss** — đủ lớp core và tổng lỗ basket ≥ % balance → đóng basket (`DCA_FULL_STACK_LOSS`).
- **Scalp TP** — chốt lệnh đơn khi đạt TP scalp.
- Volume DCA: `dca_volume_multiplier = 1.0` → mọi lớp **x1** lot (mặc định).

### Tín hiệu M5

- Weighted score: **Donchian** + **SuperTrend** + **RSI Midline** + **EMA21**.
- **RSI exhaustion** — chặn LONG/SHORT khi M5 RSI vượt `rsi_overbought` / `rsi_oversold` (mặc định **80 / 20**, chỉnh trên UI).
- **H1** xác định trend (`main_trend`); **M5** timing entry.
- Bộ lọc **ATR** giảm ngưỡng entry khi biến động cao (Normal).

### Cảnh báo Telegram

Gửi alert khi mở/đóng lệnh nếu cấu hình `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` trong `.env`.

## API

Tất cả request (trừ login) cần header `X-Secure-Key` (khớp `SECRET_KEY_DYNAMIC`, rotate mỗi 30 giây) và `Authorization: Bearer <token>` sau khi đăng nhập.

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

## Quick start (local)

Yêu cầu: **MySQL 8**, **Python 3.11+**, **Node.js 20+**, **MT5 terminal** (cho worker).

```powershell
# 1. Tạo database
# CREATE DATABASE XAUBOT CHARACTER SET utf8mb4;

# 2. Backend
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# Chỉnh DATABASE_URL, MT5_*, SECRET_KEY_DYNAMIC trong .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001

# 3. Worker (terminal riêng — MT5 đã mở)
cd backend
.\.venv\Scripts\Activate.ps1
python -m app.worker

# 4. Frontend (terminal riêng)
cd frontend
npm install
npm run dev
```

- Swagger UI: [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs)
- UI: [http://127.0.0.1:3000](http://127.0.0.1:3000) — đăng nhập `admin` / `123qwe` (bootstrap từ `.env`, tạo lần đầu khi DB trống)

> **Cổng:** Vite dev proxy trỏ tới `:8001` (`frontend/vite.config.ts`). Nếu chạy backend cổng khác, sửa `target` trong file đó hoặc set `VITE_API_URL` trong `frontend/.env`.

### Biến môi trường chính (`backend/.env`)

| Biến | Mô tả |
| ---- | ----- |
| `DATABASE_URL` | MySQL connection string |
| `MT5_PATH` / `MT5_LOGIN` / `MT5_PASSWORD` / `MT5_SERVER` | Kết nối MT5 |
| `WORKER_TICK_SECONDS` | Chu kỳ tick worker (mặc định `5`) |
| `JWT_SECRET_KEY` | Ký JWT |
| `SECRET_KEY_DYNAMIC` | Secret cho header `X-Secure-Key` (khớp frontend) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Thời hạn JWT (mặc định `480`) |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Alert Telegram (tùy chọn) |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` / `ADMIN_EMAIL` | Admin bootstrap lần đầu |

### Frontend env (`frontend/.env`)

| Biến | Mô tả |
| ---- | ----- |
| `VITE_API_URL` | URL backend (để trống khi dev — dùng Vite proxy) |
| `VITE_SECRET_KEY_DYNAMIC` | Khớp `SECRET_KEY_DYNAMIC` backend (mặc định dev: `xaubot-secure-key-dynamic-dev`) |

### MySQL

- Cài local: thường dùng `localhost:3306` (xem `backend/.env.example`).
- Docker Compose: MySQL expose `localhost:3307` → container `:3306`; cập nhật `DATABASE_URL` tương ứng.

## Worker (Windows + MT5)

- Chỉ **một** worker được phép chạy (file lock `backend/worker.lock`).
- Worker chỉ xử lý bot có `status = RUNNING`. Bật qua UI `/bot-config` hoặc `POST /api/bot/{id}/start`.
- MT5 terminal phải mở, đăng nhập broker, có chart XAUUSD.

## Test (không cần MT5)

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest tests/ -q
```

15 test modules: aggregator, basket_manager, daily_guard, execution, risk, signal_engine, supertrend, rsi_midline, telegram, …

## Trang UI

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

```powershell
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
- **Close reason phổ biến:** `CORE_BASKET_TP`, `SATELLITE_LAYER_TP`, `DCA_FULL_STACK_LOSS`, `SCALP_TP`, `POSITION_LOSS_16U`, `CLOSE_TREND_FLIP`, `CLOSE_M5_REVERSAL`.
