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
