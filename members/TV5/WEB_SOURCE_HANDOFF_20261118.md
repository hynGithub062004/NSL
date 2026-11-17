# NSL Lab Web – bản lưu tại TV5

Bộ mã nguồn Web chụp từ gói bàn giao hoàn chỉnh ngày 17/11/2026.

- `web/app.py` (FastAPI), `web/index.html`, `web/runner.py`, `web/start_windows.ps1`, `web/test_web.py`, `web/requirements.txt`, `web/README.md`, `web/__init__.py` là mã và tài liệu Web.
- `orchestrator_web.py` là module phối hợp TV5 dùng trong Web.

**Quan trọng:** Đây là bản sao mã nguồn để bàn giao, chưa được cấu hình chạy trực tiếp từ `members/TV5/web/`. Khi triển khai, cần đặt các file trong `web/` ở gốc repo và module `orchestrator_web.py` trong `members/TV5/`, đúng đường dẫn import của mã hiện tại. Không đẩy `web_data/`, `.venv/`, khóa riêng hoặc session runtime.

Các chỉnh sửa trên máy cá nhân sau thời điểm tạo gói bàn giao (nếu có) không nằm trong bản này.
