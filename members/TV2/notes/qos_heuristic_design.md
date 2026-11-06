# Thiết kế QoS-Weighted Heuristic v1

> **Trạng thái:** DRAFT triển khai phiên bản v1
> **Thành viên phụ trách:** TV2
> **Contract:** `1.0.0`
> **Tên scheduler:** `qos_heuristic`
> **Action ID:** `2`
> **Nhánh phát triển:** `feature/tv2-qos-heuristic`
> **Commit nền:** `f8fb1cc`
> **Cập nhật:** 06/11/2026

## 1. Mục tiêu

QoS-Weighted Heuristic được xây dựng nhằm khắc phục hạn chế của Queue-Based
Scheduler khi thuật toán chỉ dựa trên `queue_bits` để chia tài nguyên vô tuyến.

Kết quả baseline trước đó cho thấy Queue-Based tăng thông lượng eMBB nhưng làm
giảm chất lượng URLLC. Hạn chế thể hiện rõ nhất trong kịch bản `poor_channel`,
khi URLLC chỉ nhận trung bình khoảng `5.98 RB`, completion rate giảm xuống
khoảng `3.06%` và drop rate tăng lên khoảng `96.45%`.

QoS v1 được thiết kế với các mục tiêu:

1. Bảo vệ packet URLLC đang tiến gần deadline.
2. Tăng URLLC completion rate so với Queue-Based.
3. Giảm URLLC drop rate và độ trễ.
4. Không làm thông lượng eMBB suy giảm quá mức.
5. Phản ánh backlog của từng slice.
6. Sử dụng CQI theo đúng mô hình capacity của TV1.
7. Bảo đảm tổng phân bổ luôn bằng tổng RB của simulator.
8. Không tạo giá trị RB âm hoặc không nguyên.
9. Có tính xác định và khả năng tái lập.
10. Tạo Action đúng Contract `1.0.0`.
11. Tương thích với runner của TV2 và Orchestrator của TV5.

## 2. Phạm vi trách nhiệm

QoS v1 chỉ thực hiện luồng:

```text
State của TV1
→ kiểm tra State
→ tính backlog pressure, urgency và CQI efficiency
→ tính QoS score
→ phân bổ RB
→ tạo Action đúng Contract
```

QoS v1 không thực hiện các nhiệm vụ sau:

- Không tự sinh traffic.
- Không tự cập nhật queue.
- Không tự tạo CQI.
- Không tự tính capacity theo một mô hình riêng.
- Không tự tính lại RAN KPI.
- Không sửa State hoặc `next_state`.
- Không sửa mã nguồn RAN Simulator của TV1.
- Không huấn luyện hoặc gọi DQN của TV3.
- Không lựa chọn SRv6 path.
- Không tạo Core Policy.
- Không đo Core KPI.
- Không ghi timeout hoặc fallback metadata vào Action.

## 3. Giao diện scheduler

QoS kế thừa `BaseScheduler` và triển khai giao diện:

```python
def select_action(
    self,
    state: dict[str, Any],
    config: dict[str, Any],
    request_id: str | None = None,
) -> dict[str, Any]:
    ...
```

Tên scheduler chính thức:

```text
qos_heuristic
```

Action ID:

```text
2
```

`action_id` phải được hiểu cùng với tên scheduler:

```text
(scheduler, action_id)
```

Không được dùng riêng giá trị `2` để suy ra một phân bổ RB cố định.

Khi TV5 truyền `request_id`, QoS phải giữ nguyên `request_id` trong Action.
Khi chạy độc lập, QoS sử dụng phương thức tạo request ID xác định của
`BaseScheduler`.

## 4. State đầu vào

QoS sử dụng sáu trường chính:

```text
embb.queue_bits
embb.cqi
urllc.queue_bits
urllc.cqi
urllc.oldest_packet_delay_ms
urllc.deadline_ms
```

Các trường metadata được giữ nguyên khi tạo Action:

```text
schema_version
time_slot
scenario_id
seed
```

State mẫu thực tế đã được xác minh:

```json
{
  "schema_version": "1.0.0",
  "time_slot": 0,
  "scenario_id": "stable_load",
  "seed": 42,
  "embb": {
    "queue_bits": 17784,
    "cqi": 11
  },
  "urllc": {
    "queue_packets": 1,
    "queue_bits": 2560,
    "cqi": 8,
    "oldest_packet_delay_ms": 0.0,
    "deadline_ms": 5.0
  }
}
```

Kết quả xác minh thực tế:

- `queue_bits` là integer không âm.
- CQI là integer nằm trong `1–15`.
- `oldest_packet_delay_ms` là số không âm.
- `deadline_ms` là số dương.
- Deadline hiện tại là `5.0 ms`.
- QoS vẫn phải đọc deadline từ State, không hard-code `5.0`.
- Khi URLLC queue rỗng, delay phải bằng `0.0`.

## 5. State validation

QoS phải từ chối State trong các trường hợp:

- State không phải dictionary.
- Thiếu `schema_version`.
- Thiếu `time_slot`.
- Thiếu `scenario_id`.
- Thiếu `seed`.
- Thiếu nhánh `embb`.
- Thiếu nhánh `urllc`.
- Thiếu một trong sáu trường QoS bắt buộc.
- `queue_bits` không phải integer.
- `queue_bits` là boolean.
- `queue_bits` âm.
- CQI không phải integer.
- CQI là boolean.
- CQI nhỏ hơn `1` hoặc lớn hơn `15`.
- Delay không phải số hữu hạn.
- Delay là boolean.
- Delay âm.
- Deadline không phải số hữu hạn.
- Deadline là boolean.
- Deadline bằng `0` hoặc âm.
- `time_slot` không phải integer không âm.

Lỗi State phải được báo rõ trường không hợp lệ.

Không dùng Static fallback để che lỗi State đầu vào. Fallback chỉ áp dụng khi
scheduler bị lỗi, timeout hoặc trả Action không hợp lệ trong luồng Orchestrator.

## 6. Nguồn `slot_duration_ms`

Thời lượng slot không thuộc State Contract `1.0.0`. QoS không hard-code thời
lượng slot bằng `1 ms`. Runner đọc giá trị từ cấu hình scenario của TV1 rồi
bổ sung vào cấu hình hiệu dụng trước khi gọi scheduler.

Nguồn chính thức nằm trong cấu hình scenario của TV1:

```yaml
simulation:
  slot_duration_ms: 1
```

Runner phải đọc:

```python
ran_config["simulation"]["slot_duration_ms"]
```

và bổ sung vào cấu hình hiệu dụng truyền cho scheduler:

```python
effective_scheduler_config = copy.deepcopy(
    scheduler_config
)

effective_scheduler_config.setdefault(
    "common",
    {},
)["slot_duration_ms"] = float(
    ran_config["simulation"]["slot_duration_ms"]
)
```

QoS đọc:

```python
config["common"]["slot_duration_ms"]
```

QoS không được hard-code:

```python
slot_duration_ms = 1.0
```

Nếu thiếu hoặc giá trị không dương, QoS phải báo lỗi cấu hình.

## 7. Backlog pressure

Phương án mặc định của QoS v1:

```text
L_embb  = log1p(embb_queue_bits)
L_urllc = log1p(urllc_queue_bits)
```

`log1p` được dùng để giảm ảnh hưởng của chênh lệch backlog tuyệt đối giữa eMBB
và URLLC.

Các tính chất:

```text
queue_bits = 0
→ backlog pressure = 0

queue_bits tăng
→ backlog pressure tăng

queue_bits rất lớn
→ mức tăng score được nén theo logarithm
```

Không tính logarithm trên queue âm. Queue âm phải bị từ chối ở bước validation.

Phương án mở rộng sau pilot:

```text
rb_demand_s
=
queue_bits_s
/
max(capacity_bits(1, cqi_s), 1)

L_s = log1p(rb_demand_s)
```

Phương án dựa trên nhu cầu RB chưa dùng làm mặc định trong QoS v1. Nếu thử
nghiệm, phải dùng cấu hình riêng và không trộn kết quả với phương án mặc định.

## 8. Deadline urgency

QoS v1 sử dụng công thức:

```text
u_effective
=
clip(
    (oldest_packet_delay_ms + slot_duration_ms)
    / deadline_ms,
    0,
    1
)

urgency = u_effective²
```

Việc cộng `slot_duration_ms` phản ánh cơ hội phục vụ trong slot hiện tại.

Nếu URLLC queue rỗng:

```text
urgency = 0
```

Ví dụ với deadline `5 ms` và slot `1 ms`:

| Delay hiện tại | u_effective | urgency |
|---:|---:|---:|
| 0 ms | 0.2 | 0.04 |
| 1 ms | 0.4 | 0.16 |
| 2 ms | 0.6 | 0.36 |
| 3 ms | 0.8 | 0.64 |
| 4 ms | 1.0 | 1.00 |

Delay `4 ms` là cơ hội phục vụ cuối cùng trước khi packet có nguy cơ bị drop
trong bước age/drop tiếp theo.

QoS không sử dụng công thức cũ:

```text
urgency = (delay / deadline)²
```

vì công thức cũ không đạt urgency cực đại ở slot phục vụ cuối cùng.

## 9. Chuẩn hóa CQI

QoS không dùng chuẩn hóa tuyến tính:

```text
(cqi - 1) / 14
```

TV1 sử dụng mapping phi tuyến:

```python
CQI_SPECTRAL_EFFICIENCY = {
    1: 0.1523,
    2: 0.2344,
    3: 0.3770,
    4: 0.6016,
    5: 0.8770,
    6: 1.1758,
    7: 1.4766,
    8: 1.9141,
    9: 2.4063,
    10: 2.7305,
    11: 3.3223,
    12: 3.9023,
    13: 4.5234,
    14: 5.1152,
    15: 5.5547,
}
```

QoS v1 tái sử dụng trực tiếp mapping của TV1:

```python
from ran.rb_capacity import CQI_SPECTRAL_EFFICIENCY
```

Không sao chép bảng CQI sang TV2.

Công thức chuẩn hóa:

```text
efficiency_norm(cqi)
=
CQI_SPECTRAL_EFFICIENCY[cqi]
/
CQI_SPECTRAL_EFFICIENCY[15]
```

Các tính chất đã được kiểm tra:

- CQI `1–15` đều có trong mapping.
- Kết quả nằm trong `(0, 1]`.
- Kết quả tăng đơn điệu theo CQI.
- CQI `15` có giá trị bằng `1.0`.

Môi trường chạy test tích hợp cần có:

```bat
set "PYTHONPATH=%CD%\members\TV1\src;%CD%\members\TV2\src"
```

CQI chỉ là thành phần điều chỉnh. CQI không được lấn át deadline urgency của
URLLC.

## 10. Công thức QoS score ứng viên v1

Score eMBB:

```text
score_embb
=
w_eL × L_embb
+
w_eC × efficiency_norm(cqi_embb)
```

Score URLLC:

```text
score_urllc
=
w_uL × L_urllc
+
w_uU × urgency
+
w_uC × efficiency_norm(cqi_urllc)
```

Bộ trọng số ứng viên cho pilot:

```text
w_eL = 0.70
w_eC = 0.30

w_uL = 0.45
w_uU = 1.25
w_uC = 0.10
```

Đây là bộ trọng số ứng viên dùng cho pilot QoS v1, chưa phải bộ trọng số tối ưu
hoặc cấu hình benchmark chính thức.

Thành phần bù CQI thấp tùy chọn:

```text
w_uP
× urgency
× (1 - efficiency_norm(cqi_urllc))
```

Pilot đầu tiên tắt thành phần này:

```text
w_uP = 0.0
```

Nếu bật, phải chạy như một ablation riêng.

## 11. Bốn trạng thái queue

Trạng thái queue phải được kiểm tra trước khi tính score.

| eMBB queue | URLLC queue | Phân bổ |
|---|---|---:|
| Rỗng | Rỗng | `25/25` |
| Active | Rỗng | `50/0` |
| Rỗng | Active | `0/50` |
| Active | Active | Minimum `5/5`, chia phần còn lại theo score |

Minimum RB chỉ được áp dụng khi cả hai queue active.

Không giữ minimum RB cho slice đang rỗng.

Nhánh hai queue rỗng phải được xử lý trước khi tính CQI score. Nếu không, thành
phần CQI có thể làm score khác 0 và tạo phân bổ sai như `45/5`.

## 12. Chia RB khi hai queue active

Khi cả hai queue active:

```text
base_embb  = min_rb_embb
base_urllc = min_rb_urllc

remaining_rb
=
total_rb - min_rb_embb - min_rb_urllc
```

Với cấu hình pilot:

```text
total_rb = 50
min_rb_embb = 5
min_rb_urllc = 5
remaining_rb = 40
```

Tổng score:

```text
total_score = score_embb + score_urllc
```

Phần RB thực:

```text
embb_real
=
remaining_rb
× score_embb
/ total_score
```

```text
urllc_real
=
remaining_rb
× score_urllc
/ total_score
```

Nếu `total_score = 0`, sử dụng:

```text
25/25
```

## 13. Làm tròn và bảo toàn tổng RB

Quy tắc làm tròn là quyết định triển khai nội bộ của TV2 cho QoS v1.

> **Trạng thái quyết định:** Quyết định triển khai nội bộ của TV2 cho QoS v1.

Quy tắc làm tròn này không làm thay đổi State/Action Contract và không thuộc
các thông số giao diện bắt buộc giữa TV2 với TV1, TV3, TV4 hoặc TV5. Quy tắc
được sử dụng để chuyển phân bổ thực sang số RB nguyên, bảo đảm kết quả có tính
xác định và tổng phân bổ luôn bằng `total_rb`.

QoS sử dụng phương pháp largest remainder:

1. Tính `embb_real` và `urllc_real`.
2. Lấy phần nguyên bằng `floor`.
3. Tính fractional remainder của mỗi slice.
4. Tính số RB chưa phân bổ.
5. Cấp RB dư cho slice có fractional remainder lớn hơn.
6. Nếu remainder bằng nhau và urgency lớn hơn `0`, ưu tiên URLLC.
7. Nếu remainder bằng nhau và urgency bằng `0`, ưu tiên eMBB.
8. Cộng phần RB nền.
9. Kiểm tra tổng cuối bằng `total_rb`.

Các bất biến:

```text
rb_embb là integer
rb_urllc là integer
rb_embb >= 0
rb_urllc >= 0
rb_embb + rb_urllc = total_rb
```

Không sử dụng random.

## 14. Cấu hình QoS dự kiến

```yaml
common:
  total_rb: 50
  require_all_rb: true

qos_heuristic:
  action_id: 2
  min_rb_embb: 5
  min_rb_urllc: 5
  embb_queue_weight: 0.70
  embb_cqi_weight: 0.30
  urllc_queue_weight: 0.45
  urllc_urgency_weight: 1.25
  urllc_cqi_weight: 0.10
  low_cqi_compensation_weight: 0.0
  urgency_power: 2.0
```

`slot_duration_ms` được bổ sung vào `common` trong cấu hình hiệu dụng của runner.

QoS phải kiểm tra:

- `total_rb` là integer dương.
- Minimum RB là integer không âm.
- Tổng minimum không vượt `total_rb`.
- `slot_duration_ms` là số hữu hạn dương.
- Các weight là số hữu hạn không âm.
- `urgency_power` là số hữu hạn dương.
- `action_id` là integer không âm.

Các trọng số không được viết rải rác dưới dạng literal trong mã nguồn.

## 15. Action đầu ra

Action phải có dạng:

```json
{
  "schema_version": "1.0.0",
  "request_id": "stable_load-42-0",
  "time_slot": 0,
  "scheduler": "qos_heuristic",
  "action_id": 2,
  "rb_allocation": {
    "embb": 25,
    "urllc": 25
  }
}
```

Action không chứa:

```text
fallback_used
fallback_reason
scheduler_latency_ms
validation_latency_ms
measurement_window
Core Policy
SRv6 path
Core KPI
```

Các trường timeout, validation và fallback thuộc log của Orchestrator TV5.

## 16. Timeout, fallback và validation

Timeout `100 ms/Action` là ngưỡng thử nghiệm có cấu hình của TV5.

Timeout:

- Là thời gian wall-clock.
- Không phải `100 slot`.
- Không phải SLA RAN thời gian thực.
- Không được hard-code trong QoS.
- Không tham gia công thức QoS score.

Validation gồm hai lớp:

```text
TV2:
kiểm tra State và validate Action trước khi trả

TV5:
validate lại Contract, request_id, time_slot,
scheduler, action_id, kiểu RB và tổng RB
```

Chuỗi fallback định hướng:

```text
DQN lỗi, timeout hoặc Action sai
→ QoS

QoS lỗi, timeout hoặc Action sai
→ Static 25/25

Static lỗi
→ run thất bại rõ ràng
```

Không retry nhiều lần trong cùng một slot.

## 17. Measurement window và ranh giới Core

Measurement window thuộc phần tích hợp TV4–TV5.

Thông số dự kiến:

```text
Cửa sổ chính: 500 ms
Cửa sổ phụ: 100 ms
```

Các thông số này:

- Không tham gia QoS score.
- Không được hard-code trong `qos_heuristic.py`.
- Không thuộc Action Contract.
- Không được dùng để chuyển SR Policy theo từng slot.

QoS không:

- Chọn Path A hoặc Path B.
- Tạo locator hoặc SID.
- Tạo segment list.
- Đo RTT.
- Đo throughput Core.
- Đo packet loss Core.

TV5 ánh xạ slice sang Core Policy. TV4 thực thi và đo Core KPI.

## 18. Unit test bắt buộc

### 18.1. State validation

- Thiếu `embb.queue_bits`.
- Thiếu `embb.cqi`.
- Thiếu `urllc.queue_bits`.
- Thiếu `urllc.cqi`.
- Thiếu `oldest_packet_delay_ms`.
- Thiếu `deadline_ms`.
- Queue âm.
- Queue boolean.
- CQI bằng `0`.
- CQI lớn hơn `15`.
- Delay âm.
- Deadline bằng `0`.
- Deadline âm.
- Time slot không hợp lệ.

### 18.2. Urgency C1

- URLLC queue rỗng cho urgency bằng `0`.
- Delay `0`, deadline `5`, slot `1` cho `u_effective = 0.2`.
- Delay `2` cho `u_effective = 0.6`.
- Delay `4` cho `u_effective = 1.0`.
- Delay lớn hơn deadline được clip về `1.0`.
- Slot duration khác `1` làm urgency thay đổi đúng.
- Không hard-code slot duration.

### 18.3. CQI C2

- Import mapping TV1 thành công.
- Mapping có đủ CQI `1–15`.
- CQI `15` chuẩn hóa bằng `1`.
- Chuẩn hóa tăng đơn điệu.
- Kết quả nằm trong `(0, 1]`.
- Mapping khớp với TV1.

### 18.4. Bốn trạng thái queue C3

- Hai queue rỗng cho `25/25`.
- Chỉ eMBB active cho `50/0`.
- Chỉ URLLC active cho `0/50`.
- Cả hai active giữ minimum `5/5`.
- Không giữ minimum cho slice rỗng.

### 18.5. Hành vi QoS

- Queue bằng nhau, urgency thấp.
- Queue bằng nhau, urgency cao.
- eMBB backlog lớn, URLLC chưa khẩn cấp.
- eMBB backlog lớn, URLLC sát deadline.
- URLLC backlog lớn.
- URLLC CQI thấp và gần deadline.
- eMBB CQI cao.
- URLLC CQI cao.
- Tăng urgency không làm giảm RB URLLC khi các điều kiện khác giữ nguyên.

### 18.6. Action invariants

- Tổng RB luôn bằng `total_rb`.
- RB là integer.
- RB không âm.
- Scheduler là `qos_heuristic`.
- Action ID bằng `2`.
- Request ID được giữ nguyên.
- Time slot đúng.
- Action đạt Action Validator.
- Cùng State, config và request ID tạo cùng Action.
- Không sử dụng random.

## 19. Kế hoạch kiểm thử và benchmark

### Smoke test

```text
3 scenario
× seed 42
× 10 slot
```

### Pilot

```text
3 scenario
× seed 42
× 500 slot
```

### Benchmark QoS-only

```text
3 scenario
× 3 seed
× 1 scheduler
= 9 run
```

### So sánh cuối

```text
Static
Queue-Based
QoS-Weighted Heuristic
DQN
```

So sánh DQN chỉ thực hiện khi TV3 hoàn thiện:

- Action mapping.
- Observation.
- Reward.
- Training seed.
- Checkpoint.
- Evaluation cùng ma trận.

## 20. Điều kiện C1 đến C6

- **C1:** Urgency có cộng `slot_duration_ms`.
- **C2:** CQI chuẩn hóa theo spectral efficiency của TV1.
- **C3:** Minimum RB chỉ áp dụng khi cả hai queue active.
- **C4:** Toàn bộ tham số được config hóa và lưu trong output.
- **C5:** Request ID, determinism và Action validation đạt.
- **C6:** Khóa ma trận benchmark, cấu hình và ngưỡng suy giảm eMBB trước benchmark chính thức.

Có thể viết mã và chạy pilot trước khi khóa C6.

Không được chạy benchmark chính thức 9 run trước khi khóa C6.

## 21. Nội dung còn chờ khóa

Các nội dung chưa phải quyết định cuối:

- Bộ trọng số dùng cho benchmark chính thức.
- Ngưỡng suy giảm eMBB cho phép.
- KPI URLLC ưu tiên khi chọn cấu hình.
- Có bật low-CQI compensation hay không.
- Config ID của QoS.
- Cách ghi full QoS config vào output hoặc manifest.
- Timeout chính thức của Orchestrator.
- So sánh cuối với DQN.

Bộ trọng số hiện tại chỉ dùng cho pilot:

```text
w_eL = 0.70
w_eC = 0.30
w_uL = 0.45
w_uU = 1.25
w_uC = 0.10
w_uP = 0.0
```

Sau pilot, mọi thay đổi trọng số phải được ghi lại. Không tuning riêng theo từng
scenario và không tuning sau khi đã khóa benchmark chính thức.
