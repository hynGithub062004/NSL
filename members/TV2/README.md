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
- `QoSHeuristicScheduler`
- Cấu hình chung cho ba scheduler
- Runner tích hợp với RAN Simulator
- Matrix runner cho benchmark đa scenario và đa seed
- Script tổng hợp kết quả baseline và QoS
- Bộ kiểm thử Static, Queue-Based và QoS
- Benchmark QoS chính thức với `9/9` run hoàn thành

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

## QoS-Weighted Heuristic Scheduler

QoS-Weighted Heuristic sử dụng đồng thời:

- Backlog của eMBB và URLLC.
- Hiệu suất phổ tương ứng với CQI.
- Độ khẩn cấp của URLLC theo delay và deadline.
- Minimum RB động theo trạng thái queue.

QoS sử dụng:

```text
scheduler = qos_heuristic
action_id = 2
```

Quy tắc phân bổ theo trạng thái queue:

| eMBB queue | URLLC queue | Quy tắc |
|---:|---:|---|
| 0 | 0 | Phân bổ `25/25 RB` |
| > 0 | 0 | Phân bổ `50/0 RB` |
| 0 | > 0 | Phân bổ `0/50 RB` |
| > 0 | > 0 | Mỗi slice nhận tối thiểu `5 RB` |

Khi cả hai queue active, phần RB còn lại được phân bổ dựa trên backlog
pressure, CQI efficiency và URLLC urgency. Phương pháp largest remainder được
sử dụng để chuyển phân bổ thực sang RB nguyên và bảo toàn tổng `50 RB`.

Thiết kế chi tiết được trình bày trong:

- `notes/qos_heuristic_design.md`

## Tạo môi trường

Từ thư mục `members/TV2`:

    conda env create -f environment/environment_tv2.yml
    conda activate nsl-tv2-py311

## Chạy kiểm thử

    python -m unittest discover -s tests -v
    python -m pytest tests -q

Kết quả dự kiến với `unittest`:

    Ran 53 tests
    OK

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

- So sánh QoS-Weighted Heuristic với DQN trên cùng ma trận đánh giá.
- Bàn giao giao diện scheduler cho Orchestrator.
- Tích hợp scheduler với luồng điều phối liên thành viên.
- Đánh giá ảnh hưởng của SRv6 path và Core Policy khi các thành phần tương ứng
  được tích hợp.
- Rà soát tài liệu bàn giao và Pull Request của TV2.

## Chạy tích hợp với RAN Simulator

Runner tích hợp hỗ trợ ba scheduler:

- `static`
- `queue_based`
- `qos_heuristic`

Ví dụ chạy Static từ thư mục `members/TV2`:

    python scripts/run_scheduler_baseline.py ^
      --scheduler static ^
      --scenario-config ../TV1/configs/stable_load.yaml ^
      --scheduler-config configs/schedulers.yaml ^
      --seed 42 ^
      --slots 500 ^
      --output local_results/stable_load/static/seed_42

Thay `static` bằng `queue_based` hoặc `qos_heuristic` để chạy scheduler tương
ứng.

Ví dụ chạy QoS từ thư mục gốc repository:

    python members\TV2\scripts
un_scheduler_baseline.py ^
      --scheduler qos_heuristic ^
      --scenario-config members\TV1\configs\stable_load.yaml ^
      --scheduler-config members\TV2\configs\schedulers.yaml ^
      --seed 42 ^
      --slots 500 ^
      --output local_results\qos_example

Runner lấy `simulation.slot_duration_ms` từ cấu hình scenario của TV1 rồi đưa
vào cấu hình hiệu dụng của scheduler. Giá trị này không được hard-code trong
`schedulers.yaml`.

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

    python members\TV2\scripts
un_baseline_matrix.py ^
      --schedulers static queue_based ^
      --slots 500 ^
      --seeds 42 43 44 ^
      --output-root local_resultsaseline_matrix

Script thực hiện các kiểm tra:

- Mỗi run hoàn thành đủ số slot.
- Packet conservation đạt.
- Static luôn phân bổ `25/25 RB`.
- Queue-Based luôn sử dụng đủ `50 RB`.
- Queue-Based cấp tối thiểu `5 RB` cho mỗi slice.
- Static và Queue-Based nhận cùng traffic với cùng scenario và seed.
- Đủ các tệp đầu ra của RAN Simulator.

Kết quả chạy thô được lưu cục bộ trong:

    local_resultsaseline_matrix

Thư mục `local_results` không được đưa vào Git.

### Tổng hợp kết quả benchmark

Sau khi ma trận hoàn thành, chạy:

    python members\TV2\scripts\summarize_baseline_results.py ^
      --input-root local_resultsaseline_matrix ^
      --output-dir members\TV2
esults ^
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

Với cùng scenario và seed, các scheduler phải nhận cùng:

- `arrived_embb_bits`
- `arrived_urllc_bits`
- `offered_embb_mbps`
- `offered_urllc_mbps`

Nếu các giá trị đầu vào này không giống nhau, kết quả không được sử dụng để
so sánh scheduler.

## Benchmark QoS-Weighted Heuristic

Benchmark QoS chính thức sử dụng:

- Scheduler: `qos_heuristic`.
- Scenario: `stable_load`, `urllc_burst`, `poor_channel`.
- Seed: `42`, `43`, `44`.
- Số slot mỗi run: `500`.
- Tổng số lần chạy: `9`.

### Chạy ma trận QoS

Từ thư mục gốc repository:

    python members\TV2\scripts
un_baseline_matrix.py ^
      --schedulers qos_heuristic ^
      --seeds 42 43 44 ^
      --slots 500 ^
      --output-root local_results\qos_official

Nếu thư mục `local_results\qos_official` đã tồn tại, matrix runner sẽ từ chối
ghi đè. Không sử dụng `--overwrite` đối với dữ liệu benchmark chính thức đã
được nghiệm thu.

Kết quả hợp lệ cần kết thúc bằng:

    SCHEDULER MATRIX: 9/9 RUNS PASS

### Tổng hợp kết quả QoS

    python members\TV2\scripts\summarize_qos_results.py ^
      --input-root local_results\qos_official ^
      --output-dir members\TV2
esults ^
      --expected-slots 500

Script tạo:

- `results/qos_runs.csv`
- `results/qos_aggregate.csv`

Báo cáo phân tích được lưu tại:

- `results/qos_analysis.md`

### Kết quả QoS chính thức

| Scenario | eMBB throughput (Mbps) | URLLC completion | URLLC drop | Mean delay (ms) |
|---|---:|---:|---:|---:|
| `stable_load` | 13.237833 | 0.877511 | 0.120720 | 1.837906 |
| `urllc_burst` | 11.854193 | 0.633974 | 0.361688 | 2.852276 |
| `poor_channel` | 3.911875 | 0.440394 | 0.555656 | 3.919765 |

Trên trung bình ba seed, QoS có completion rate cao hơn, drop rate thấp hơn và
mean delay thấp hơn Queue-Based trong cả ba scenario.

Mức suy giảm eMBB so với Queue-Based là:

- `stable_load`: `9.68%`
- `urllc_burst`: `4.37%`
- `poor_channel`: `28.96%`

Mức suy giảm lớn nhất là `28.96%`, thấp hơn giới hạn C6 là `35%`. QoS cũng duy
trì eMBB throughput cao hơn Static trong cả ba scenario.

Bộ trọng số QoS v1 đạt phạm vi benchmark hiện tại nhưng chưa được chứng minh
là cấu hình tối ưu.
