# Phân tích kết quả QoS-Weighted Heuristic v1

## 1. Phạm vi đánh giá

QoS-Weighted Heuristic v1 được đánh giá trên ba kịch bản chính thức của
RAN Simulator:

- `stable_load`
- `urllc_burst`
- `poor_channel`

Mỗi kịch bản được chạy với ba seed:

```text
42, 43, 44
```

Mỗi run gồm:

```text
500 slot × 1 ms/slot
```

Tổng số lần chạy QoS chính thức:

```text
3 scenario × 3 seed × 1 scheduler = 9 run
```

Cấu hình QoS được giữ nguyên trong toàn bộ benchmark. Không thực hiện tuning
riêng theo scenario hoặc seed.

## 2. Tính hợp lệ của dữ liệu

Toàn bộ chín run đều đạt các điều kiện:

- `status = complete`.
- `processed_slots = 500`.
- `scheduler = qos_heuristic`.
- `action_id = 2`.
- Tổng phân bổ trong mỗi Action bằng `50 RB`.
- RB là số nguyên và không âm.
- Packet conservation đạt.
- Không có tổ hợp scenario, seed và scheduler bị trùng.
- Mỗi run có đủ `500` transition.

Kết quả chi tiết được lưu trong:

```text
members/TV2/results/qos_runs.csv
```

Kết quả tổng hợp ba seed được lưu trong:

```text
members/TV2/results/qos_aggregate.csv
```

## 3. KPI trung bình của QoS v1

| Scenario | eMBB throughput (Mbps) | URLLC throughput (Mbps) | Completion rate | Drop rate | Mean delay (ms) | P95 delay (ms) | Mean eMBB RB | Mean URLLC RB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `stable_load` | 13.237833 | 3.534605 | 0.877511 | 0.120720 | 1.837906 | 4.000000 | 34.042000 | 15.958000 |
| `urllc_burst` | 11.854193 | 3.463576 | 0.633974 | 0.361688 | 2.852276 | 5.000000 | 34.614667 | 15.385333 |
| `poor_channel` | 3.911875 | 2.264928 | 0.440394 | 0.555656 | 3.919765 | 5.000000 | 31.235333 | 18.764667 |

Kết quả cho thấy lượng RB cấp cho URLLC thay đổi theo trạng thái của hệ thống.
URLLC nhận trung bình nhiều RB nhất trong `poor_channel`, tương ứng với điều
kiện kênh bất lợi và mức backlog, urgency cao hơn.

## 4. So sánh với Static và Queue-Based

### 4.1. Kịch bản `stable_load`

| Scheduler | eMBB throughput (Mbps) | URLLC completion | URLLC drop | Mean delay (ms) |
|---|---:|---:|---:|---:|
| Static | 10.201256 | 0.928010 | 0.071554 | 1.623657 |
| Queue-Based | 14.657110 | 0.614115 | 0.381038 | 3.298156 |
| QoS v1 | 13.237833 | 0.877511 | 0.120720 | 1.837906 |

So với Queue-Based, QoS giảm eMBB throughput khoảng `9.68%`, nhưng completion
rate URLLC tăng khoảng `26.34` điểm phần trăm, drop rate giảm khoảng `26.03`
điểm phần trăm và mean delay giảm khoảng `44.27%`.

So với Static, QoS tăng eMBB throughput khoảng `29.77%`, trong khi completion
rate URLLC thấp hơn khoảng `5.05` điểm phần trăm. Kết quả cho thấy QoS duy trì
được mức cân bằng giữa thông lượng eMBB và chất lượng phục vụ URLLC.

### 4.2. Kịch bản `urllc_burst`

| Scheduler | eMBB throughput (Mbps) | URLLC completion | URLLC drop | Mean delay (ms) |
|---|---:|---:|---:|---:|
| Static | 10.034249 | 0.688174 | 0.308864 | 2.614067 |
| Queue-Based | 12.395556 | 0.517337 | 0.477317 | 3.109899 |
| QoS v1 | 11.854193 | 0.633974 | 0.361688 | 2.852276 |

So với Queue-Based, QoS giảm eMBB throughput khoảng `4.37%`, nhưng completion
rate URLLC tăng khoảng `11.66` điểm phần trăm, drop rate giảm khoảng `11.56`
điểm phần trăm và mean delay giảm khoảng `8.28%`.

QoS duy trì eMBB throughput cao hơn Static khoảng `18.14%`. Trong điều kiện
traffic URLLC xuất hiện theo burst, QoS vẫn bảo vệ URLLC tốt hơn Queue-Based
mà không làm giảm đáng kể thông lượng eMBB.

### 4.3. Kịch bản `poor_channel`

| Scheduler | eMBB throughput (Mbps) | URLLC completion | URLLC drop | Mean delay (ms) |
|---|---:|---:|---:|---:|
| Static | 3.139449 | 0.591555 | 0.404952 | 3.191722 |
| Queue-Based | 5.506769 | 0.030612 | 0.964541 | 4.758140 |
| QoS v1 | 3.911875 | 0.440394 | 0.555656 | 3.919765 |

`poor_channel` là kịch bản thể hiện rõ nhất vai trò của QoS. So với
Queue-Based, completion rate URLLC tăng khoảng `40.98` điểm phần trăm, drop
rate giảm khoảng `40.89` điểm phần trăm và mean delay giảm khoảng `17.62%`.

eMBB throughput giảm khoảng `28.96%` so với Queue-Based, nhưng vẫn cao hơn
Static khoảng `24.60%`. Mức suy giảm này vẫn nằm trong giới hạn C6 là `35%`.

## 5. Kiểm tra điều kiện C6

| Điều kiện | `stable_load` | `urllc_burst` | `poor_channel` |
|---|---|---|---|
| Completion cao hơn Queue-Based | Đạt | Đạt | Đạt |
| Drop thấp hơn Queue-Based | Đạt | Đạt | Đạt |
| Mean delay không cao hơn Queue-Based | Đạt | Đạt | Đạt |
| Suy giảm eMBB không quá 35% | Đạt, 9.68% | Đạt, 4.37% | Đạt, 28.96% |
| eMBB cao hơn Static | Đạt | Đạt | Đạt |
| Packet conservation | Đạt | Đạt | Đạt |
| Action Contract | Đạt | Đạt | Đạt |

Toàn bộ điều kiện C6 đều đạt trên trung bình ba seed của từng scenario.

Mức suy giảm eMBB lớn nhất so với Queue-Based là khoảng `28.96%` trong
`poor_channel`, thấp hơn giới hạn `35%` đã khóa trước benchmark chính thức.
QoS đồng thời cải thiện completion rate, drop rate và mean delay của URLLC
trong cả ba scenario.

## 6. Phân tích hành vi phân bổ RB

QoS v1 không giữ minimum RB cho slice đang rỗng. Khi URLLC queue rỗng, toàn bộ
`50 RB` có thể được cấp cho eMBB. Khi cả hai queue active, mỗi slice được giữ
minimum `5 RB`, sau đó phần RB còn lại được chia theo backlog pressure, CQI và
deadline urgency.

Phân bổ RB trung bình cho URLLC là:

```text
stable_load:  15.958000 RB
urllc_burst:  15.385333 RB
poor_channel: 18.764667 RB
```

Trong `poor_channel`, QoS tăng lượng RB trung bình của URLLC để phản ứng với
backlog và urgency cao hơn. Việc tăng tài nguyên cho URLLC giúp completion rate
tăng đáng kể so với Queue-Based, vốn chỉ cấp trung bình khoảng `5.86 RB` cho
URLLC trong cùng kịch bản baseline.

Lượng RB trung bình dành cho eMBB vẫn nằm trong khoảng `31.24` đến `34.61 RB`.
Kết quả này giải thích vì sao QoS duy trì được thông lượng eMBB cao hơn Static,
trong khi vẫn cải thiện các KPI URLLC so với Queue-Based.

## 7. Hạn chế

Kết quả hiện tại có các giới hạn sau:

- Benchmark chỉ sử dụng ba seed `42`, `43`, `44`.
- Bộ trọng số QoS v1 là cấu hình pilot đã khóa, chưa được chứng minh là tối ưu.
- P95 delay thường đạt sát deadline `5 ms`, nên completion rate, drop rate và
  mean delay có khả năng phân biệt scheduler tốt hơn P95.
- QoS được đánh giá trên RAN Simulator hiện tại và chưa bao gồm ảnh hưởng của
  SRv6 path hoặc Core Policy.
- Chưa thực hiện so sánh chính thức với DQN trên cùng ma trận đánh giá.
- Ngưỡng suy giảm eMBB `35%` là tiêu chí thiết kế được khóa cho benchmark này,
  không phải ngưỡng phổ quát cho mọi hệ thống RAN.
- Các kết quả chỉ phản ánh cấu hình traffic, channel và capacity model trong
  phạm vi mô hình hiện tại.

## 8. Kết luận

QoS-Weighted Heuristic v1 đạt mục tiêu cân bằng giữa eMBB throughput và chất
lượng URLLC. Thuật toán cải thiện completion rate, drop rate và mean delay của
URLLC so với Queue-Based trong cả ba scenario, đồng thời duy trì eMBB
throughput cao hơn Static.

Mức suy giảm eMBB lớn nhất so với Queue-Based là khoảng `28.96%` trong
`poor_channel`, vẫn thấp hơn giới hạn C6 là `35%`. Toàn bộ chín run đạt packet
conservation và Action Contract.

Kết quả benchmark cho thấy cấu hình QoS v1 hiện tại đủ điều kiện được sử dụng
làm cấu hình benchmark chính thức của TV2 và làm baseline heuristic cho bước
so sánh với DQN sau này. Kết quả này không đồng nghĩa với việc bộ trọng số hiện
tại là tối ưu, nhưng xác nhận thuật toán đã đạt các mục tiêu và ràng buộc được
khóa trong phạm vi đánh giá.
