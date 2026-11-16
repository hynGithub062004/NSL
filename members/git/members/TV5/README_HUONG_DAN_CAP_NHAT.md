# TV5: bản kiểm chứng tích hợp thực TV1 + TV2, sẵn sàng TV3, chờ TV4

Đây là bản **bổ sung dành cho thư mục `members/TV5/`**, không thay thế repository NSL của nhóm. Nó dựa vào các file **đang có** trong NSL-main.zip ngày 25/10/2026. Không ghi đè phần TV1–TV4.

## Cài đặt

1. Giải nén repo `NSL-main.zip`, mở thư mục gốc `NSL-main` trong VS Code.
2. Sao chép `integration_runner.py` và thư mục `tests/` từ bộ ZIP này vào `members/TV5/` (giữ nguyên TV5 README hiện có).
3. Từ thư mục gốc repo, tạo virtualenv Python 3.11, rồi `python -m pip install pytest jsonschema pyyaml`.
4. Nếu muốn **chạy DQN thật**, bổ sung `gymnasium stable-baselines3 torch` phiên bản khớp TV3, xem `members/TV3/README.md` và kiểm tra checkpoint.

## Chạy

Từ **thư mục gốc NSL-main**:

```powershell
python -m pytest members/TV1/tests members/TV2/tests members/TV5/tests -q
python members/TV5/integration_runner.py --scheduler static --scenario stable_load --seed 42 --slots 10
python members/TV5/integration_runner.py --scheduler queue_based --scenario urllc_burst --seed 42 --slots 10
python members/TV5/integration_runner.py --scheduler dqn --scenario poor_channel --seed 42 --slots 10
```

Nếu DQN không tải được do thiếu dependencies, chương trình thông báo lỗi (không tự tạo kết quả giả). Muốn thử lỗi/fallback DEMO dùng `--allow-fallback`: dùng **Static thật TV2** thay DQN, ghi rõ `fallback_used=True`, và KHÔNG dùng dữ liệu này để chứng minh hiệu quả DQN.

Để chạy benchmark thực RAN đủ 500 slots/scenario/seed, **bỏ `--slots 10`**, chạy với các seed 42 43 44 và các scenario stable_load, urllc_burst, poor_channel.

## Tệp đầu ra

- `results/integration_stage1/<scenario>/<scheduler>/seed_<n>/ran/`: toàn bộ export TV1 nguyên gốc.
- `unified_without_core.csv`: dữ liệu RAN thực; cột Core KPI để trống, `core_status=NOT_CONNECTED`.
- `handoff_with_slice_id.jsonl`: hai entry mỗi slot, gồm metadata `slice_id` ở wrapper và payload **đúng** `core_handoff.schema.json` bên trong. Đây là vật liệu bàn giao TV4, **chưa có Core API**.
- `tv5_status.json`: tóm tắt và tình trạng fallback.

## Các vấn đề phải chốt với nhóm

1. TV1 `contracts/*.schema.json` version 1.0.0 là nguồn dữ liệu chính thức. Không tự ý sửa.
2. `action_id` phụ thuộc scheduler, **không áp bảng DQN** lên TV2 Static hay Queue-Based.
3. TV2 chưa có file `qos_heuristic.py`, nên không tuyên bố đã có fallback QoS. Tạm dùng Static thật và ghi nhãn.
4. TV4 hiện mới có README; phải bàn giao topology/script/API và Core KPI thực.
5. Schema `core_handoff` chưa có `slice_id`. Nhóm phải thống nhất một contract TV5–TV4 đủ nhận diện slice/flow và chọn policy tương ứng; nếu sửa bản TV1 đang khóa thì phải làm quy trình versioning.
6. Network slicing E2E phải đảm bảo eMBB và URLLC có thể được steering vào policy tương ứng **đồng thời**, không phải đổi một default route chung qua lại.
7. Khi TV4 trả KPI thực, lưu join key: `seed, scenario_id, algorithm, time_slot, request_id` và thêm `slice_id` ở bảng TV5 cho kết quả 2 slice. Không phép đo Core thật nào được đưa vào cột trống mà không xác nhận origin, unit và phạm vi đo.
8. Không ghép trực tiếp delay RAN/RTT Core thành một E2E latency nếu chưa đồng bộ định nghĩa và thời điểm đo.

## Roadmap sau script này

Tạo module adapter vào `orchestrator/` để kết nối TV1/TV2/TV3 từ Python in-process hoặc JSONL bridge của TV1; giữ đối tượng DQN nạp một lần; thêm FastAPI, route chuyển SR Policy đến TV4, retry/fallback có log, `smoke_test.py`, `run_benchmark.py`, `generate_report.py`. Bộ TV5 starter trước đó chỉ dùng để tham khảo cấu trúc, **không dùng nguyên schema/action map**.
