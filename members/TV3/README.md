# TV3 — DQN Scheduler for Network Slicing

## 1. Tổng quan

TV3 xây dựng mô hình Deep Q-Network (DQN) để phân bổ Resource Block (RB) giữa hai network slice **eMBB và URLLC**.

- **Môi trường:** Gymnasium kết nối trực tiếp RANSimulator của TV1.
- **Thuật toán:** DQN (Stable-Baselines3).
- **Contract:** `1.0.0`.
- **Checkpoint cho benchmark hiện hành:** [`models/dqn_v3_best.zip`](models/dqn_v3_best.zip).
- **Kết quả đã kiểm tra:** 42/42 kiểm thử TV3, 9/9 lượt benchmark DQN v3 và 36/36 lượt so sánh bốn scheduler.
- **DQN v2:** Checkpoint và kết quả cũ được lưu để tái lập thí nghiệm trước đây. Các báo cáo dùng DQN v3 lấy số liệu từ `results/benchmark_v3/` và `results/rb_analysis_v3/`.

TV3 không tự sinh traffic, CQI hoặc tính lại KPI. Toàn bộ dữ liệu mô phỏng và KPI được lấy từ TV1.

## 2. Tham số mô phỏng chung

| Tham số | Giá trị |
|---|---|
| Tổng tài nguyên | 50 RB |
| Slot duration | 1 ms |
| Simulation duration | 500 slots (500 ms/run) |
| Resource elements/RB | 168 |
| Overhead factor | 0.75 |
| CQI hợp lệ | 1–15 |
| URLLC packet size | 2.560 bits |
| URLLC deadline | 5 ms |
| Seed của thuật toán DQN | 100 |
| Seed mô phỏng cho episode huấn luyện | `100000 + episode_index` (chỉ số bắt đầu từ 0) |
| Seed mô phỏng cho validation | 200101, 200102, 200103 |
| Seed mô phỏng chỉ dùng cho benchmark | 42, 43, 44 |

**Kịch bản mô phỏng:**

| Scenario | eMBB traffic | URLLC traffic | CQI |
|---|---|---|---|
| `stable_load` | 18.000 bits/slot | 1,5 packet/slot | 3–15 |
| `urllc_burst` | 16.000 bits/slot | 1 packet/slot, burst ×6 | 3–15 |
| `poor_channel` | 12.000 bits/slot | 1,5 packet/slot | 1–8 |

Các tham số được đọc từ YAML trong `members/TV1/configs/`. DQN v3 được huấn luyện trên `urllc_burst`. Ba seed validation được lặp lại ở mỗi mốc đánh giá để chọn checkpoint trong cùng điều kiện. Benchmark cuối dùng cả ba kịch bản.

## 3. Cấu hình DQN

| Hyperparameter | Giá trị |
|---|---|
| Algorithm | DQN |
| Policy | MlpPolicy |
| Total timesteps | 50.000 |
| Learning rate | 0.001 |
| Replay buffer | 20.000 |
| Learning starts | 1.000 |
| Batch size | 64 |
| Discount factor (γ) | 0.99 |
| Target update interval | 200 |
| Exploration fraction | 0.3 |
| Evaluation frequency | 2.500 timesteps |
| Evaluation episodes | 3 |
| Inference | `deterministic=True` |

### Observation Space

State đầu vào DQN gồm 5 giá trị đã chuẩn hóa:

| Thành phần | Công thức |
|---|---|
| eMBB queue | `min(queue_bits / 250000, 1)` |
| eMBB CQI | `cqi / 15` |
| URLLC queue | `min(queue_bits / 100000, 1)` |
| URLLC CQI | `cqi / 15` |
| URLLC urgency | `min(oldest_packet_delay_ms / deadline_ms, 1)` |

Observation Space: `Box(0, 1, shape=(5,))`.

### Action Space

DQN sử dụng `Discrete(5)`:

| Action ID | eMBB RB | URLLC RB |
|---|---:|---:|
| 0 | 10 | 40 |
| 1 | 20 | 30 |
| 2 | 25 | 25 |
| 3 | 30 | 20 |
| 4 | 40 | 10 |

Tổng RB luôn bằng 50.

### Reward Function

```python
reward = (
    min(throughput_e / 20.0, 1.0)
    - 0.4 * min(delay_u / deadline_ms, 1.0)
    - 1.5 * drop_u
    - 1.5 * sla_violation
)
```

Mục tiêu: tăng thông lượng eMBB, đồng thời hạn chế độ trễ, tỷ lệ drop và vi phạm SLA của URLLC.

Các giá trị throughput, delay, drop và SLA được lấy từ KPI của TV1.

## 4. File chính và kết quả

| File/Thư mục | Chức năng |
|---|---|
| [`network_slicing_env.py`](network_slicing_env.py) | Môi trường Gymnasium kết nối RANSimulator của TV1 |
| [`train_dqn.py`](train_dqn.py) | Huấn luyện DQN v3 và đánh giá theo ba seed validation cố định |
| [`evaluate_dqn.py`](evaluate_dqn.py) | Benchmark DQN v3 trên 9 lượt và đối chiếu lưu lượng đầu vào với Static của TV2 |
| [`plot_results.py`](plot_results.py) | Vẽ 7 biểu đồ KPI của DQN v3 |
| [`scripts/compare_rb_4_schedulers.py`](scripts/compare_rb_4_schedulers.py) | So sánh Static, Queue-Based, QoS-Weighted (`qos_heuristic`) và DQN v3 |
| [`dqn_scheduler.py`](dqn_scheduler.py) | Adapter suy luận dùng trong benchmark và tích hợp TV5 |
| [`models/dqn_v3_best.zip`](models/dqn_v3_best.zip) | Checkpoint validation tốt nhất tại bước 30.000 |
| [`results/training_v3/`](results/training_v3/) | Log huấn luyện, seed từng episode, kết quả validation và [manifest chứa SHA-256](results/training_v3/training_manifest.json) |
| [`results/benchmark_v3/`](results/benchmark_v3/) | [CSV từng lượt](results/benchmark_v3/dqn_runs.csv), [CSV tổng hợp](results/benchmark_v3/dqn_aggregate.csv) và manifest benchmark |
| [`results/rb_analysis_v3/`](results/rb_analysis_v3/) | [CSV từng lượt](results/rb_analysis_v3/rb_efficiency_runs.csv), [CSV tổng hợp](results/rb_analysis_v3/rb_efficiency_aggregate.csv) và [chỉ số từng slot](results/rb_analysis_v3/rb_slot_metrics.csv) |
| [`figures/benchmark_v3/`](figures/benchmark_v3/) và [`figures/training_v3/`](figures/training_v3/) | Biểu đồ KPI benchmark và biểu đồ huấn luyện |
| [`docs/DQN_API_HANDOFF.md`](docs/DQN_API_HANDOFF.md) | Tài liệu Contract và API suy luận |

Kết quả v2 nằm tại `results/dqn_runs.csv`, `results/dqn_aggregate.csv`, `results/training_v2/` và `results/rb_analysis/`.

## 5. Hướng dẫn chạy

Chạy các lệnh từ thư mục gốc `NSL`. Hai lệnh benchmark dưới đây dùng thư mục đầu ra mới để chạy lại phép đo cùng checkpoint và lưu riêng kết quả. Nếu thư mục chạy lại đã có CSV, chọn đường dẫn đầu ra mới.

**Chạy kiểm thử**

```powershell
python -m pytest members/TV3/tests -v
```

**Đánh giá checkpoint DQN v3 và vẽ biểu đồ**

```powershell
python members/TV3/evaluate_dqn.py --model members/TV3/models/dqn_v3_best.zip --output members/TV3/results/benchmark_v3_rerun
python members/TV3/plot_results.py --input members/TV3/results/benchmark_v3_rerun/dqn_aggregate.csv --output members/TV3/figures/benchmark_v3_rerun
```

**So sánh bốn scheduler**

```powershell
python members/TV3/scripts/compare_rb_4_schedulers.py --model members/TV3/models/dqn_v3_best.zip --output members/TV3/results/rb_analysis_v3_rerun
```

Hai script benchmark xác minh SHA-256 của checkpoint theo manifest huấn luyện trước khi chạy. Phép so sánh bốn scheduler kiểm tra lưu lượng đầu vào và bảo toàn RB trên 36 lượt.

**Huấn luyện lại DQN v3 khi cần tạo checkpoint mới**

```powershell
python members/TV3/train_dqn.py --timesteps 50000 --seed 100
```

Script dừng nếu đã có checkpoint hoặc manifest v3 tại đường dẫn mặc định. Để huấn luyện lại, lưu bộ kết quả hiện có ở vị trí khác trước khi chạy.

## 6. Hướng dẫn tích hợp cho TV5

TV5 có thể gọi trực tiếp Scheduler như sau:

```python
from members.TV3.dqn_scheduler import DQNScheduler

scheduler = DQNScheduler(
    model_path="members/TV3/models/dqn_v3_best.zip",
    total_rb=50
)

action = scheduler.predict(
    state=state_from_tv1,
    request_id="req-000125"
)
```

**Input:** State Contract `1.0.0` từ TV1, bao gồm queue, CQI, deadline và time_slot.

**Ví dụ cấu trúc Output:**

```json
{
  "schema_version": "1.0.0",
  "request_id": "req-000125",
  "time_slot": 125,
  "scheduler": "dqn",
  "action_id": 0,
  "rb_allocation": {
    "embb": 10,
    "urllc": 40
  }
}
```

TV5 nhận Action để kiểm tra và truyền tới RAN Simulator. TV3 không tự gọi `apply_action()` hoặc điều khiển SRv6.

**Lưu ý khi tích hợp:** Truyền rõ `model_path` để chạy v3 vì mặc định hiện tại của adapter là checkpoint v2. Dùng Contract `1.0.0` với cấu hình 50 RB. Nếu thay đổi tổng RB, cần kiểm tra lại mô hình và tập hành động.

## 7. Trạng thái và giới hạn

- DQN v3 hoàn tất 50.000 bước huấn luyện. Checkpoint tại bước 30.000 đạt reward validation trung bình −49,8015.
- Benchmark DQN v3 gồm 3 kịch bản × 3 seed, mỗi lượt 500 slot.
- So sánh 4 scheduler gồm 36 lượt, tổng cộng 18.000 slot. Tỷ lệ sử dụng RB bằng số RB thực dùng chia cho số RB khả dụng. Jain(service) đo mức công bằng theo KPI dịch vụ của TV1. Jain(RB) đo mức cân bằng phân bổ RB.
- Khi đánh giá QoS, đọc tỷ lệ sử dụng RB cùng thông lượng eMBB, tỷ lệ hoàn thành và tỷ lệ rớt URLLC. Độ trễ URLLC của DQN v3 nằm trong CSV benchmark và bộ biểu đồ KPI.
- Các kết quả trên được đo ở RAN Simulator. Việc đánh giá End-to-End với Core SRv6 cần phép đo tích hợp TV4/TV5.

**Phân công liên quan:** TV1 cung cấp RAN State/KPI; TV2 cung cấp baseline; TV3 cung cấp DQN Scheduler/checkpoint; TV4 phụ trách SRv6; TV5 điều phối tích hợp End-to-End.
