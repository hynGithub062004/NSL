# TV1 – Dữ liệu đầu vào cho phép đo End-to-End (bàn giao TV4, TV5)

Phiên bản tệp xuất: `e2e_export_version = 1.0.0`. Hai tệp này **bổ sung** vào
đầu ra của `export_results()`. Chúng không thay đổi các contract State, Action,
KPI và Transition đã đóng băng ở `schema_version 1.0.0`. Kết quả mô phỏng cũ
không đổi: `ran_metrics.csv` và `transitions.jsonl` giống hệt từng byte, và
`run_id` của lượt smoke stable_load vẫn là `2031495362859ef7`.

## 1. Thay đổi mã

| Tệp | Nội dung |
|---|---|
| `src/ran/simulator.py` | `_prepare_slot()` ghi mỗi gói URLLC khi sinh ra. `apply_action()` gọi `_record_e2e_slot()` để ghi số bit eMBB thực tế đã phục vụ trong khe, các gói hoàn tất, các gói bị rớt, và cập nhật số bit còn lại của gói đang chờ. `export_results()` xuất thêm `ran_urllc_packets.csv` và `ran_embb_slots.csv`. |
| `scripts/run_ran.py` | Thêm tham số `--scheduler` để gán nhãn cho Action cố định (ví dụ `static`). In thêm `run_id`. |
| `scripts/validate_handoff.py` | Đối chiếu hai tệp mới với `ran_metrics.csv`, `run_summary.json` và `run_manifest.json`. |
| `tests/test_ran.py` | Thêm 3 kiểm thử E2E. Tổng cộng 17 kiểm thử (14 cũ + 3 mới), tất cả đạt. |

## 2. Quy ước thời gian (bắt buộc dùng thống nhất)

- Đơn vị thời gian: **ms**, tính từ mốc bắt đầu lượt chạy `t0 = 0 ms`.
- Khe đầu tiên mang số **0**. Khe `t` chiếm khoảng `[t·T, (t+1)·T)` với
  `T = slot_duration_ms = 1 ms`.
- Lưu lượng đến vào **đầu khe**: `arrival_time_ms = arrival_slot · T`.
- Dữ liệu được phục vụ trong khe `t` được phát tại **cuối khe**:
  `emit_time_ms = (t + 1) · T`.
  Ví dụ: gói hoàn tất ở cuối khe 9 được phát tại mốc **10 ms**.
- Với URLLC: `emit_time_ms − arrival_time_ms = delay_ms`. Giá trị này khớp với
  `completed_urllc_delay_ms` trong `run_summary.json`.
- Gói rớt ở khe `d` khi tuổi của gói chạm deadline:
  `(d + 1) · T = deadline_time_ms`.

## 3. `ran_urllc_packets.csv` (mỗi dòng là một gói URLLC)

| Cột | Đơn vị | Ý nghĩa |
|---|---|---|
| `e2e_export_version` | – | `1.0.0` |
| `run_id` | – | Giống `run_manifest.json` |
| `seed`, `scenario_id` | – | Khóa ghép |
| `packet_id` | – | `u-00000001`, … theo thứ tự sinh |
| `arrival_slot` / `arrival_time_ms` | khe / ms | Khe sinh gói / thời điểm gói đến |
| `size_bits` | bit | Kích thước gói (2560) |
| `deadline_ms` / `deadline_time_ms` | ms | Hạn trễ / mốc hết hạn tuyệt đối |
| `final_status` | – | `completed`, `dropped` hoặc `unresolved` (gói còn chờ khi lượt chạy kết thúc) |
| `completion_slot` | khe | Khe hoàn tất (trống nếu gói không hoàn tất) |
| `drop_slot` | khe | Khe bị rớt (trống nếu gói không bị rớt) |
| `resolved_slot` | khe | `completion_slot` hoặc `drop_slot` |
| `resolved_request_id`, `resolved_algorithm` | – | Action của khe chốt số phận gói (khóa ghép với TV4) |
| `served_bits` / `remaining_bits` | bit | Số bit đã phục vụ / còn lại (gói rớt có thể đã được phục vụ một phần) |
| `delay_ms` | ms | Trễ hoàn tất (chỉ có với `completed`) |
| `emit_time_ms` | ms | Thời điểm TV4 phát gói (chỉ có với `completed`) |

**TV4 chỉ phát các gói `completed`**, mỗi gói `size_bits` bit, tại mốc
`emit_time_ms`. Gói `dropped` và `unresolved` không được phát.

## 4. `ran_embb_slots.csv` (mỗi dòng là một khe)

| Cột | Đơn vị | Ý nghĩa |
|---|---|---|
| `e2e_export_version`, `run_id`, `seed`, `scenario_id` | – | Như trên |
| `algorithm`, `request_id`, `time_slot` | – | Khóa ghép, giống `ran_metrics.csv` |
| `slot_start_ms`, `slot_end_ms` | ms | Biên của khe |
| `emit_time_ms` | ms | Bằng `slot_end_ms`, là thời điểm phát lượng bit của khe |
| `embb_cqi`, `allocated_embb_rb`, `used_embb_rb` | –, RB | Điều kiện kênh và tài nguyên |
| `capacity_bits` | bit | Dung lượng phục vụ tối đa của khe |
| `arrival_bits` | bit | Số bit đến trong khe |
| `queue_before_bits` / `queue_after_bits` | bit | Hàng đợi trước / sau phục vụ |
| `served_embb_bits` | bit | **Số bit thực tế đã phục vụ trong khe**, đây là lượng TV4 phải phát |

`served_embb_bits ≤ min(capacity_bits, queue_before_bits)` và
`queue_after_bits = queue_before_bits − served_embb_bits`. Số bit có thể không
chia hết cho 8. Nếu cần byte, TV4 nên cộng dồn và làm tròn ở mức luồng thay vì
làm tròn từng khe.

## 5. Kiểm thử đã chạy

```powershell
python scripts\run_ran.py --config configs\stable_load.yaml --seed 42 --embb-rb 25 --urllc-rb 25 --scheduler static --output results\e2e_stable_load_static_seed42
python scripts\validate_handoff.py --results results\e2e_stable_load_static_seed42 --total-rb 50
python -m unittest discover -s tests -v
```

Kết quả với stable_load, Static 25/25, seed 42, 500 khe (`run_id 1af89363d533655e`):

| Đối chiếu | Tệp mới | Tham chiếu | Khớp |
|---|---:|---:|:-:|
| Tổng bit eMBB đã phục vụ | 3 816 904 | `served_embb_bits` (ran_metrics và run_summary) = 3 816 904 | ✔ |
| Gói URLLC sinh ra | 764 | `arrived` = 764 | ✔ |
| Hoàn tất | 730 | `completed` = 730 | ✔ |
| Rớt | 33 | `dropped` = 33 | ✔ |
| Còn chờ | 1 | `unresolved_at_end` = 1 | ✔ |
| Kiểm thử RAN | 17/17 đạt (14 cũ + 3 mới) | | ✔ |

Kết quả lưu tại `results/e2e_stable_load_static_seed42/`.
