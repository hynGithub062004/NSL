# TV2 - Scheduler

Đây là khu vực upload riêng của thành viên TV2.

Phạm vi chính: đọc `State`, tạo `Action`, triển khai các thuật toán
scheduler và xây dựng kiểm thử liên quan. TV2 giữ nguyên tên trường
theo schema trong `../TV1/contracts/` và không thay đổi logic của
RAN Simulator.

## Môi trường

- Python 3.11.16
- Conda environment: `nsl-tv2-py311`
- Data Contract: `1.0.0`

## Nội dung đã hoàn thành

- `BaseScheduler`
- `Action Validator`
- `StaticScheduler`
- `QueueBasedScheduler`
- Cấu hình scheduler
- Ví dụ chạy Queue-Based
- Bộ kiểm thử Static và Queue-Based

## Static Scheduler

Static Scheduler phân bổ cố định:

- eMBB: 25 RB
- URLLC: 25 RB
- Tổng: 50 RB

## Queue-Based Scheduler

Queue-Based Scheduler đọc:

- `embb.queue_bits`
- `urllc.queue_bits`

Mỗi slice được cấp tối thiểu 5 RB. Phần RB còn lại được chia
theo tỷ lệ hàng đợi. Tổng phân bổ luôn bằng 50 RB.

Một số trường hợp đã kiểm tra:

- Queue `(0, 0)` cho phân bổ `25/25`
- Queue `(1000, 1000)` cho phân bổ `25/25`
- Queue `(3000, 1000)` cho phân bổ `35/15`
- Queue `(1000, 3000)` cho phân bổ `15/35`
- Queue `(0, 5000)` cho phân bổ `5/45`
- Queue `(5000, 0)` cho phân bổ `45/5`

## Tạo môi trường

Từ thư mục `members/TV2`:

    conda env create -f environment/environment_tv2.yml
    conda activate nsl-tv2-py311

## Chạy kiểm thử

    python -m unittest discover -s tests -v
    python -m pytest tests -q

Kết quả dự kiến:

    Ran 24 tests
    OK

    24 passed

## Chạy ví dụ Queue-Based

Trên Windows CMD:

    set PYTHONPATH=%CD%\src
    python examples\demo_queue_based.py

Kết quả cuối:

    ALL QUEUE-BASED CASES: PASS

## Quan hệ với TV1

TV2 sử dụng State và Action Contract do TV1 bàn giao trong
`../TV1/contracts/`. TV2 không thay đổi traffic, queue, CQI,
capacity, deadline hoặc cách tính KPI trong RAN Simulator.

## Công việc tiếp theo

- Tích hợp Static và Queue-Based với RAN Simulator
- Chạy thử nghiệm trên các kịch bản chung
- So sánh KPI giữa Static và Queue-Based
- Phát triển QoS-Weighted Heuristic
- Bàn giao giao diện scheduler cho Orchestrator

## Chạy tích hợp với RAN Simulator

Runner tích hợp hỗ trợ Static và Queue-Based Scheduler:

    python scripts/run_scheduler_baseline.py ^
      --scheduler static ^
      --scenario-config ../TV1/configs/stable_load.yaml ^
      --scheduler-config configs/schedulers.yaml ^
      --seed 42 ^
      --slots 500 ^
      --output local_results/stable_load/static/seed_42

Thay `static` bằng `queue_based` để chạy Queue-Based Scheduler.

Runner sử dụng trực tiếp `RANSimulator` của TV1, kiểm tra Action trước
khi áp dụng và dùng `export_results()` của TV1 để xuất KPI. Runner không
sửa tệp cấu hình gốc và không tự tính lại KPI.

## Benchmark Static và Queue-Based Scheduler

TV2 cung cấp công cụ chạy benchmark tự động cho hai scheduler truyền thống:

- `static`
- `queue_based`

Benchmark chính thức sử dụng:

- Ba kịch bản:
  - `stable_load`
  - `urllc_burst`
  - `poor_channel`
- Ba seed:
  - `42`
  - `43`
  - `44`
- `500` time slot cho mỗi lần chạy.
- Tổng cộng `18` lần chạy.

### Chạy toàn bộ ma trận benchmark

Từ thư mục gốc repository, chạy:

    python members\TV2\scripts\run_baseline_matrix.py ^
      --slots 500 ^
      --seeds 42 43 44 ^
      --output-root local_results\baseline_matrix

Script thực hiện các kiểm tra:

- Mỗi run hoàn thành đủ số slot.
- Packet conservation đạt.
- Static luôn phân bổ `25/25 RB`.
- Queue-Based luôn sử dụng đủ `50 RB`.
- Queue-Based cấp tối thiểu `5 RB` cho mỗi slice.
- Static và Queue-Based nhận cùng traffic với cùng scenario và seed.
- Đủ các tệp đầu ra của RAN Simulator.

Kết quả chạy thô được lưu cục bộ trong:

    local_results\baseline_matrix

Thư mục `local_results` không được đưa vào Git.

### Tổng hợp kết quả benchmark

Sau khi ma trận hoàn thành, chạy:

    python members\TV2\scripts\summarize_baseline_results.py ^
      --input-root local_results\baseline_matrix ^
      --output-dir members\TV2\results ^
      --expected-slots 500

Script tổng hợp tạo hai tệp:

- `results/baseline_runs.csv`
- `results/baseline_aggregate.csv`

`baseline_runs.csv` chứa kết quả chi tiết của `18` lần chạy.

`baseline_aggregate.csv` chứa giá trị trung bình, độ lệch chuẩn mẫu, giá trị
nhỏ nhất và lớn nhất qua ba seed cho từng cặp scenario và scheduler.

### Tài liệu phân tích

Kết quả và nhận xét kỹ thuật được trình bày trong:

- `results/baseline_analysis.md`

Phân tích baseline tập trung vào:

- Thông lượng eMBB.
- Thông lượng URLLC.
- URLLC completion rate.
- URLLC drop rate.
- Độ trễ URLLC.
- Phân bổ RB trung bình.
- Hạn chế của Queue-Based Scheduler.
- Yêu cầu thiết kế QoS-Weighted Heuristic.

### Lưu ý về tính công bằng

KPI được lấy trực tiếp từ RAN Simulator của TV1. TV2 không tự tính lại
throughput, delay hoặc packet drop.

Với cùng scenario và seed, Static cùng Queue-Based phải nhận cùng:

- `arrived_embb_bits`
- `arrived_urllc_bits`
- `offered_embb_mbps`
- `offered_urllc_mbps`

Nếu các giá trị đầu vào này không giống nhau, kết quả không được sử dụng để
so sánh scheduler.
