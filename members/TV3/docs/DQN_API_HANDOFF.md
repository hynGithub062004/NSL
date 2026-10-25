# TV3 — DQN Scheduler API Handoff

**Project:** Network Slicing với RAN Scheduler, DQN, SRv6 và Orchestrator  
**Module:** Thành viên 3 — Deep Q-Network Scheduler  
**Contract Version:** 1.0.0  
**Status:** TV1–TV3 Integration Tested  
**Python Version Tested:** 3.11.9

## 1. Mục đích

Tài liệu mô tả giao diện DQN Scheduler do Thành viên 3 phát triển, phục vụ tích hợp với Orchestrator của Thành viên 5.

DQN Scheduler nhận State do RAN Simulator của TV1 cung cấp, sử dụng checkpoint đã huấn luyện để lựa chọn phương án phân bổ Resource Blocks (RB), sau đó trả về Action theo Contract 1.0.0.

TV3 không tự sinh traffic, không thay đổi queue, không tính lại RAN KPI và không điều khiển SRv6 Core.

## 2. Cấu trúc module

Các file chính:

- `network_slicing_env.py`: Gymnasium Environment và hàm chuẩn hóa Observation.
- `train_dqn.py`: Huấn luyện DQN và xuất Reward/Loss.
- `evaluate_dqn.py`: Đánh giá DQN theo các scenario và seed chung.
- `dqn_scheduler.py`: Adapter phục vụ tích hợp với TV5.
- `models/dqn_v2_best.zip`: Checkpoint sử dụng để suy luận.
- `results/dqn_runs.csv`: Kết quả của từng lần đánh giá.
- `results/dqn_aggregate.csv`: Kết quả tổng hợp qua ba seed.
- `tests/test_dqn_scheduler.py`: Unit Test.
- `tests/test_dqn_integration.py`: Integration Test với TV1.

## 3. Giao diện DQN Scheduler

### 3.1. Khởi tạo

```python
from members.TV3.dqn_scheduler import DQNScheduler

scheduler = DQNScheduler()
```

Mặc định, Scheduler sử dụng checkpoint tại:

`members/TV3/models/dqn_v2_best.zip`

Checkpoint được nạp một lần khi khởi tạo đối tượng.

### 3.2. Hàm suy luận

```python
action = scheduler.predict(
    state=state,
    request_id=request_id
)
```

**Input:**

- `state`: Dictionary tuân thủ TV1 State Contract 1.0.0.
- `request_id`: Chuỗi định danh do Orchestrator truyền vào.

**Output:** Dictionary Action tuân thủ TV1 Action Contract 1.0.0.

Scheduler hoạt động ở chế độ suy luận xác định (`deterministic=True`).

## 4. State đầu vào

Các trường bắt buộc:

| Trường | Kiểu dữ liệu | Mô tả |
|---|---|---|
| schema_version | String | Phiên bản Contract |
| time_slot | Integer | Slot hiện tại |
| scenario_id | String | Tên kịch bản |
| seed | Integer | Seed mô phỏng |
| embb.queue_bits | Integer | Backlog eMBB |
| embb.cqi | Integer | CQI eMBB |
| urllc.queue_packets | Integer | Số packet URLLC trong queue |
| urllc.queue_bits | Integer | Backlog URLLC |
| urllc.cqi | Integer | CQI URLLC |
| urllc.oldest_packet_delay_ms | Number | Tuổi packet URLLC lâu nhất |
| urllc.deadline_ms | Number | Deadline URLLC |

CQI nằm trong khoảng 1–15. Các trường queue không âm và deadline phải dương.

## 5. Observation của DQN

DQN v2 sử dụng Observation 5 chiều:

1. eMBB backlog chuẩn hóa.
2. eMBB CQI chuẩn hóa.
3. URLLC backlog chuẩn hóa.
4. URLLC CQI chuẩn hóa.
5. URLLC deadline urgency.

Việc chuyển State thành Observation sử dụng trực tiếp `NetworkSlicingEnv._extract_obs()`.

TV5 không tự chuẩn hóa Observation để tránh sai lệch với mô hình đã huấn luyện.

## 6. Action Space

DQN sử dụng không gian hành động `Discrete(5)`.

Với tổng tài nguyên 50 RB:

| action_id | eMBB RB | URLLC RB |
|---|---:|---:|
| 0 | 10 | 40 |
| 1 | 20 | 30 |
| 2 | 25 | 25 |
| 3 | 30 | 20 |
| 4 | 40 | 10 |

Tất cả Action phải có tổng phân bổ bằng 50 RB.

Action được tạo thông qua hàm `make_action()` của TV3.

## 7. Action Contract

Ví dụ một kết quả suy luận thực tế từ smoke test:

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

`request_id` được giữ nguyên từ phía gọi Scheduler.

`time_slot` lấy trực tiếp từ State của TV1.

## 8. Xử lý lỗi

Scheduler kiểm tra đầu vào trước khi suy luận.

Các trường hợp không hợp lệ bao gồm:

- Thiếu trường State bắt buộc.
- Sai phiên bản Contract.
- CQI ngoài khoảng 1–15.
- Queue âm hoặc sai kiểu dữ liệu.
- Deadline không dương hoặc không hữu hạn.
- Checkpoint không tồn tại.
- Observation hoặc Action không hợp lệ.

Trong các trường hợp lỗi, Scheduler phát sinh Exception.

TV5 chịu trách nhiệm bắt Exception, ghi log và kích hoạt phương án fallback theo chính sách đã thống nhất giữa các thành viên.

TV3 không tự kích hoạt fallback bên trong DQN Scheduler.

## 9. Thông số mô phỏng chung

| Thông số | Giá trị |
|---|---|
| Contract | 1.0.0 |
| Tổng tài nguyên | 50 RB |
| Slot duration | 1 ms |
| Slots/run | 500 |
| Benchmark seeds | 42, 43, 44 |
| Scenarios | stable_load, urllc_burst, poor_channel |
| CQI | 1–15 |
| URLLC deadline | 5 ms trong ba scenario hiện tại |

TV1 là nguồn dữ liệu chính thức đối với traffic, CQI, service và KPI.

## 10. Kết quả kiểm thử

### Unit Test

Lệnh:

```bash
python -m pytest members/TV3/tests/test_dqn_scheduler.py -v
```

Kết quả ghi nhận:

**26 passed in 5.25s**

### Integration Test TV1–TV3

Lệnh:

```bash
python -m pytest members/TV3/tests/test_dqn_integration.py -v
```

Kết quả ghi nhận:

**9 passed in 5.51s**

Integration Test sử dụng ba scenario, ba seed và 500 slot cho mỗi lần chạy.

Tổng số slot kiểm thử tích hợp: 4.500.

Các kiểm thử xác nhận Action hợp lệ, không thay đổi State đầu vào, phân bổ đúng tổng RB và Packet Conservation được bảo toàn.

## 11. Ranh giới trách nhiệm

**TV1:** Quản lý RAN Simulator, traffic, CQI, queue, phục vụ packet và RAN KPI.

**TV3:** Huấn luyện DQN, suy luận Action, bảo đảm dữ liệu đầu vào và đầu ra phù hợp Contract.

**TV5:** Điều phối Scheduler, quản lý request_id, kiểm tra Action, đo thời gian suy luận, xử lý lỗi và fallback.

**TV4:** Quản lý SRv6 Core Policy và Core KPI.

## 12. Nội dung cần xác nhận khi tích hợp TV5

- Cách khởi tạo và duy trì đối tượng DQNScheduler.
- Chính sách timeout cho mỗi lần suy luận.
- Validator Action chính thức của Orchestrator.
- Cơ chế fallback từ DQN sang QoS Heuristic hoặc Static.
- Định dạng log khi Scheduler lỗi.
- Quản lý checkpoint và phiên bản mô hình khi triển khai.

## 13. Giới hạn hiện tại

TV3 đã hoàn thành kiểm thử độc lập và tích hợp với TV1.

Chưa xác nhận tích hợp End-to-End với Orchestrator TV5 và SRv6 Core TV4.

Kết quả benchmark DQN hiện chưa đủ để khẳng định DQN tốt hơn tất cả các thuật toán truyền thống hoặc QoS Heuristic.

Việc so sánh cuối cùng phải sử dụng cùng RAN Simulator, scenario, seed, cách tính KPI và phiên bản mã nguồn.

---

**Kết luận:** DQN Scheduler Adapter đã sẵn sàng để TV5 tiếp nhận và bắt đầu kiểm thử tích hợp. Việc nghiệm thu End-to-End chỉ được thực hiện sau khi các giao diện và chính sách điều phối được xác nhận chung.