# API TV5 V2

Chạy từ gốc repo: `python -m uvicorn members.TV5.api_v2:app --host 127.0.0.1 --port 8001`. Mở `/docs` để xem schema request thực tế. Tạo session ví dụ:

```json
{"scheduler":"qos_heuristic","scenario":"urllc_burst","seed":42,"slots":10,"allow_fallback":false}
```

Gọi `GET /sessions/{run_id}/state`, `POST /sessions/{run_id}/decision`, `POST /sessions/{run_id}/step`, sau đó `GET /sessions/{run_id}/metrics`. `POST /sessions/{run_id}/run-to-end` hoàn thành các slot còn lại. `allow_fallback=true` dùng DQN → QoS → Static khi DQN thất bại và ghi lý do.

`GET /core/health`, `/core/policies`, `/core/events`, `/core/kpi/{slice_id}` đọc TV4 qua `TV4_CORE_URL` (mặc định `http://127.0.0.1:18018`). KPI lịch sử không được coi là phép đo mới. `/sessions/{run_id}/core-plan` chỉ lập kế hoạch. Core Apply có router trong `core_apply_v2.py`; chỉ dùng với xác nhận, readback và controller lab TV4 đang chạy; không tự đổi policy mỗi slot.

Web tích hợp dùng `orchestrator_web.py` với API `/api/tv5/sessions` ở cổng 8080. Đây là một triển khai session riêng của web, không phải proxy sang cổng 8001. Test: `python -m pytest members/TV5/tests web/test_tv5.py -q`.
