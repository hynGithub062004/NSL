# TV5 Integration

Mã TV5 từ bản bàn giao `NSL 16.11.26` được đặt trực tiếp trong thư mục này. Thư mục lồng `TV5/TV5` cũ đã được thay thế. Các file `results/`, bản sao lưu và `__pycache__` trong ZIP là dữ liệu từ máy gốc, không phải mã triển khai; Git history vẫn lưu bản cũ.

## Chạy API TV5

Từ thư mục gốc repo, với môi trường Python có các thư viện TV1–TV3:

```powershell
python -m pip install -r members/TV5/requirements-api-v2.txt
python -m pytest members/TV5/tests -q
python -m uvicorn members.TV5.api_v2:app --host 127.0.0.1 --port 8001
```

`/sessions` tạo RAN session; `/state`, `/decision`, `/step`, `/run-to-end`, `/metrics` điều phối theo slot. Scheduler gồm Static, Queue-based, QoS Heuristic và DQN. Fallback DQN → QoS → Static ghi nhãn thuật toán thực tế trong log. `core_apply_v2.py` có Core plan và controlled Apply qua API TV4; cần xác nhận riêng và readback.

## Web và bàn giao TV4

Web chạy từ `web/`, gọi `members/TV5/orchestrator_web.py` cho các nút TV5. Bộ benchmark web vẫn gọi TV1/TV2/TV3 trực tiếp, độc lập với session TV5. Agent đo Core của web nằm ở `members/TV4/controller/tv4_web_agent.py`.

`handover/NSL_TV5_update_for_running_web.zip` chỉ chứa ba file cần chép đè lên web TV4 đang chạy; `handover/Huong_dan_TV4_cap_nhat_web_va_kiem_thu_TV5.docx` mô tả thao tác và bằng chứng cần lưu. Nếu cài trên máy mới từ Git, dùng toàn bộ `web/` và `web/README.md`.

Kết quả chạy mới nằm trong `web_data/` hoặc `members/TV5/results/` và không được commit tự động.
