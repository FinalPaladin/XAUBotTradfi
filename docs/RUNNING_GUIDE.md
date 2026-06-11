# Hướng dẫn chạy local — API, Worker, UI

Tài liệu này mô tả cách khởi động **3 thành phần** của XAUBot trên máy Windows:

| Thành phần | Mô tả | Cổng |
| ---------- | ----- | ---- |
| **API** | Backend FastAPI | `8001` |
| **Worker** | Trading loop (Windows + MT5) | — |
| **UI** | React + Vite | `3000` |

Chạy **3 terminal PowerShell riêng**. Thứ tự khuyến nghị: **MySQL → API → Worker → UI**.

---

## Yêu cầu trước khi chạy

1. **MySQL** đang chạy và đã tạo database:

   ```sql
   CREATE DATABASE XAUBOT CHARACTER SET utf8mb4;
   ```

2. **Backend `.env`** — copy từ `backend/.env.example` và chỉnh `DATABASE_URL`, MT5:

   ```powershell
   cd D:\Bot\backend
   copy .env.example .env
   ```

3. **Python venv + dependencies** (lần đầu):

   ```powershell
   cd D:\Bot\backend
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

4. **Frontend dependencies** (lần đầu):

   ```powershell
   cd D:\Bot\frontend
   npm install
   ```

5. **Worker** — MT5 terminal đã mở, đăng nhập broker (Exness / Bybit TradFi), có chart XAUUSD.

---

## Terminal 1 — API (Backend)

```powershell
cd D:\Bot\backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

- Swagger UI: [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs)
- Health check: [http://127.0.0.1:8001/health](http://127.0.0.1:8001/health)

> **Cổng:** Vite dev proxy trỏ tới `:8001` (`frontend/vite.config.ts`). Nếu đổi cổng API, sửa `target` trong file đó hoặc set `VITE_API_URL` trong `frontend/.env`.

### MySQL

| Cách chạy | Host / port | Ghi chú |
| --------- | ----------- | ------- |
| Cài local | `localhost:3306` | Mặc định trong `.env.example` |
| Docker Compose | `localhost:3307` | Container map `3307 → 3306`; cập nhật `DATABASE_URL` |

---

## Terminal 2 — Worker

```powershell
cd D:\Bot\backend
.\.venv\Scripts\Activate.ps1
python -m app.worker
```

Worker chỉ xử lý bot có `status = RUNNING`. Bật bot qua UI (`/bot-config`) hoặc API:

```http
POST /api/bot/{bot_id}/start
```

### Biến môi trường MT5 (`backend/.env`)

| Biến | Mô tả |
| ---- | ----- |
| `MT5_PATH` | Đường dẫn `terminal64.exe` |
| `MT5_LOGIN` | Login (để trống = dùng terminal hiện tại) |
| `MT5_PASSWORD` | Password |
| `MT5_SERVER` | Server broker |
| `WORKER_TICK_SECONDS` | Chu kỳ tick worker (mặc định `5`) |

---

## Terminal 3 — UI (Frontend)

```powershell
cd D:\Bot\frontend
npm run dev
```

- Mở: [http://127.0.0.1:3000](http://127.0.0.1:3000)
- Đăng nhập: `admin` / `123qwe` (hardcode, chưa có auth API)
- UI proxy `/api` và `/health` → `http://127.0.0.1:8001` — **API phải chạy trước**

### Trang chính

| Route | Mô tả |
| ----- | ----- |
| `/` | Dashboard — P&L, lệnh mở |
| `/positions` | Lệnh đang mở, đóng lệnh |
| `/history` | Lịch sử đã đóng |
| `/bot-config` | Cấu hình bot |
| `/exchanges` | Thông tin sàn MT5 |
| `/logs` | System logs |

---

## Tóm tắt nhanh

```
Terminal 1 (API):    cd backend → activate venv → uvicorn ... --port 8001
Terminal 2 (Worker): cd backend → activate venv → python -m app.worker
Terminal 3 (UI):   cd frontend → npm run dev
```

---

## Chạy bằng Docker (tùy chọn)

Không bao gồm Worker (Worker cần Windows + MT5 local):

```powershell
cd D:\Bot\backend
docker compose up --build
```

- API: [http://localhost:8000](http://localhost:8000)
- UI: [http://localhost:3000](http://localhost:3000)
- MySQL: `localhost:3307` (user `root`, password `123qwe`, DB `XAUBOT`)

---

## Test (không cần MT5)

```powershell
cd D:\Bot\backend
.\.venv\Scripts\Activate.ps1
pytest tests/ -q
```

---

## Xử lý lỗi thường gặp

| Triệu chứng | Gợi ý |
| ----------- | ----- |
| `Another worker holds the lock. Exiting.` | Đã có **một worker khác đang chạy** — chỉ được 1 instance. Xem mục bên dưới |
| UI không gọi được API | Kiểm tra API đang chạy cổng `8001`; xem tab Network trên trình duyệt |
| Worker thoát ngay (MT5) | Kiểm tra MT5 đã mở, `MT5_PATH` đúng, `.env` hợp lệ |
| API lỗi DB | MySQL đang chạy, database `XAUBOT` đã tạo, `DATABASE_URL` đúng |
| `Activate.ps1` bị chặn | Chạy `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` (một lần) |

### Lỗi `Another worker holds the lock`

Worker dùng file lock `backend/worker.lock` để **chỉ cho phép 1 process** chạy cùng lúc (tránh double-trade).

**Nguyên nhân thường gặp:** bạn mở thêm terminal thứ 2 chạy `python -m app.worker`, hoặc worker cũ vẫn chạy ngầm từ lần trước.

**Kiểm tra worker đang chạy:**

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='python3.11.exe'" |
  Where-Object { $_.CommandLine -match 'app\.worker' } |
  Select-Object ProcessId, CommandLine
```

**Cách xử lý:**

1. Tìm terminal đang chạy worker → nhấn `Ctrl+C` để dừng sạch (lock tự giải phóng).
2. Hoặc kill process theo PID (thay `12345` bằng PID thực tế):

   ```powershell
   Stop-Process -Id 12345 -Force
   ```

3. Chỉ khi **chắc chắn không còn worker nào** mà vẫn lỗi (worker crash trước đó): xóa lock thủ công:

   ```powershell
   Remove-Item D:\Bot\backend\worker.lock -Force
   ```

   > Không xóa `worker.lock` khi còn worker đang chạy — sẽ có 2 worker trade song song.

Sau đó chạy lại:

```powershell
cd D:\Bot\backend
.\.venv\Scripts\Activate.ps1
python -m app.worker
```
