# TV3 — DQN Scheduler for Network Slicing

## 1. Tổng quan

TV3 xây dựng mô hình Deep Q-Network (DQN) để phân bổ Resource Block (RB) giữa hai network slice **eMBB và URLLC**.

- **Môi trường:** Gymnasium kết nối trực tiếp RANSimulator của TV1.
- **Thuật toán:** DQN (Stable-Baselines3).
- **Contract:** `1.0.0`.
- **Checkpoint sử dụng:** `models/dqn_v2_best.zip`.
- **Trạng thái:** Hoàn thành huấn luyện, đánh giá và kiểm thử tích hợp TV1–TV3 (37/37 tests passed).

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
| Benchmark seeds | 42, 43, 44 |
| Training seed | 100 |
| Validation seed | 101 |

**Kịch bản mô phỏng:**

| Scenario | eMBB traffic | URLLC traffic | CQI |
|---|---|---|---|
| `stable_load` | 18.000 bits/slot | 1,5 packet/slot | 3–15 |
| `urllc_burst` | 16.000 bits/slot | 1 packet/slot, burst ×6 | 3–15 |
| `poor_channel` | 12.000 bits/slot | 1,5 packet/slot | 1–8 |

Các tham số được đọc từ YAML trong `members/TV1/configs/`. TV1 là nguồn cấu hình chính thức.

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
| `network_slicing_env.py` | Gymnasium Environment |
| `train_dqn.py` | Huấn luyện và lưu Reward/Loss |
| `evaluate_dqn.py` | Đánh giá DQN trên 9 lần chạy |
| `plot_results.py` | Vẽ 7 biểu đồ KPI |
| `dqn_scheduler.py` | API suy luận để TV5 tích hợp |
| `models/dqn_v2_best.zip` | Checkpoint tốt nhất theo Evaluation |
| `results/dqn_runs.csv` | Kết quả từng scenario/seed |
| `results/dqn_aggregate.csv` | Kết quả trung bình và độ lệch chuẩn |
| `results/training_v2/` | Training Reward, Loss, Evaluation Reward |
| `figures/` | 7 biểu đồ KPI và 3 biểu đồ huấn luyện |
| `docs/DQN_API_HANDOFF.md` | Tài liệu API chi tiết |

## 5. Hướng dẫn chạy

Tất cả lệnh chạy từ thư mục gốc `NSL`.

**Huấn luyện lại DQN (chỉ chạy khi cần):**

```powershell
python members/TV3/train_dqn.py --timesteps 50000 --seed 100
```

Lưu ý: Lệnh này có thể ghi đè checkpoint DQN v2 hiện tại.

**Đánh giá checkpoint:**

```powershell
python members/TV3/evaluate_dqn.py --model members/TV3/models/dqn_v2_best.zip
```

**Vẽ lại biểu đồ KPI:**

```powershell
python members/TV3/plot_results.py
```

**Chạy kiểm thử:**

```powershell
python -m pytest members/TV3/tests -v
```

Kết quả đã kiểm tra: **37 passed** gồm 26 Unit Tests, 9 Integration Tests và 2 Environment Tests.

## 6. Hướng dẫn tích hợp cho TV5

TV5 có thể gọi trực tiếp Scheduler như sau:

```python
from members.TV3.dqn_scheduler import DQNScheduler

scheduler = DQNScheduler(
    model_path="members/TV3/models/dqn_v2_best.zip",
    total_rb=50
)

action = scheduler.predict(
    state=state_from_tv1,
    request_id="req-000125"
)
```

**Input:** State Contract `1.0.0` từ TV1, bao gồm queue, CQI, deadline và time_slot.

**Output mẫu đã kiểm thử:**

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

**Lưu ý khi tích hợp:** Cần dùng đúng checkpoint, phiên bản Contract và cấu hình 50 RB. Nếu cấu hình tổng RB thay đổi, phải xác nhận lại tính tương thích của mô hình và tập hành động.

## 7. Trạng thái và giới hạn

- Đã huấn luyện DQN v2 với 50.000 timesteps.
- Đã đánh giá 3 scenario × 3 seed (9 runs, 500 slots/run).
- Đã xuất CSV tương thích cấu trúc benchmark TV2.
- Đã kiểm thử Adapter với TV1: 37/37 tests passed.
- Đã có log Training Reward, Loss và Evaluation Reward.
- Chưa hoàn thành tích hợp End-to-End với TV5/TV4.
- Chưa kết luận DQN vượt trội hơn tất cả baseline; cần so sánh KPI cuối cùng trên cùng dữ liệu và seed.

**Phân công liên quan:** TV1 cung cấp RAN State/KPI; TV2 cung cấp baseline; TV3 cung cấp DQN Scheduler/checkpoint; TV4 phụ trách SRv6; TV5 điều phối tích hợp End-to-End.