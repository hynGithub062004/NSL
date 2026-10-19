# Phân tích benchmark Static và Queue-Based Scheduler

## 1. Mục tiêu

Benchmark được thực hiện nhằm đánh giá hai thuật toán lập lịch truyền thống do Thành viên 2 phát triển trên cùng môi trường RAN Simulator của Thành viên 1:

- Static Scheduler.
- Queue-Based Scheduler.

Các mục tiêu chính gồm:

1. Kiểm tra khả năng hoạt động ổn định của hai scheduler trên nhiều kịch bản.
2. Bảo đảm Static và Queue-Based nhận cùng traffic và điều kiện kênh khi so sánh.
3. Kiểm tra Action có tuân thủ Contract và các ràng buộc tài nguyên hay không.
4. Đánh giá sự đánh đổi giữa thông lượng eMBB và chất lượng dịch vụ URLLC.
5. Phân tích ảnh hưởng của tải ổn định, tải URLLC dạng burst và điều kiện kênh xấu.
6. Xác định ưu điểm và hạn chế của từng scheduler.
7. Tạo baseline chính thức làm cơ sở phát triển QoS-Weighted Heuristic.
8. Chuẩn bị dữ liệu đối chiếu với DQN Scheduler trong giai đoạn tiếp theo.
9. Cung cấp dữ liệu để Orchestrator lựa chọn scheduler và thiết kế fallback.

Benchmark này chỉ đánh giá hai scheduler truyền thống trong phạm vi RAN Simulator. Benchmark chưa bao gồm DQN Scheduler, Core KPI của mạng SRv6 hoặc cơ chế điều phối đầu cuối của Orchestrator.

## 2. Điều kiện thực nghiệm

Các lần chạy sử dụng chung các điều kiện:

- Contract: `1.0.0`.
- Tổng tài nguyên: `50 RB`.
- Thời lượng một time slot: `1 ms`.
- Số time slot mỗi lần chạy: `500`.
- Scheduler:
  - `static`
  - `queue_based`
- Kịch bản:
  - `stable_load`
  - `urllc_burst`
  - `poor_channel`
- Seed đánh giá:
  - `42`
  - `43`
  - `44`

Tổng số lần chạy chính thức:

```text
3 kịch bản × 3 seed × 2 scheduler = 18 lần chạy
```

Mỗi lần chạy sử dụng cùng một phiên bản RAN Simulator, State/Action Contract, cấu hình scheduler và công thức KPI. TV2 không tự sinh traffic, không tự cập nhật queue, không tự tạo CQI và không tự tính lại throughput, delay hoặc packet drop.

### 2.1. Cấu hình Static Scheduler

Static Scheduler sử dụng phân bổ cố định:

```text
eMBB  = 25 RB
URLLC = 25 RB
Tổng  = 50 RB
```

Static không thay đổi phân bổ theo queue, CQI, delay hoặc deadline.

### 2.2. Cấu hình Queue-Based Scheduler

Queue-Based Scheduler:

1. Cấp tối thiểu `5 RB` cho eMBB.
2. Cấp tối thiểu `5 RB` cho URLLC.
3. Chia `40 RB` còn lại theo tỷ lệ `queue_bits`.
4. Bảo đảm tổng phân bổ luôn bằng `50 RB`.
5. Nếu hai queue cùng bằng 0, phân bổ `25/25`.
6. Không sử dụng số ngẫu nhiên khi tạo Action.

Queue-Based hiện chỉ sử dụng:

```text
state["embb"]["queue_bits"]
state["urllc"]["queue_bits"]
```

Thuật toán chưa sử dụng trực tiếp CQI, độ trễ của gói cũ nhất hoặc deadline.

## 3. Quy trình benchmark

Benchmark được thực hiện bằng hai script:

```text
members/TV2/scripts/run_baseline_matrix.py
members/TV2/scripts/summarize_baseline_results.py
```

### 3.1. Script chạy ma trận

`run_baseline_matrix.py` thực hiện:

1. Lặp qua ba scenario.
2. Lặp qua ba seed.
3. Chạy cả Static và Queue-Based.
4. Gọi lại logic của `run_scheduler_baseline.py`.
5. Kiểm tra run summary và run manifest.
6. Kiểm tra số transition.
7. Kiểm tra phân bổ RB.
8. Kiểm tra packet conservation.
9. Kiểm tra hai scheduler dùng cùng traffic đầu vào.
10. Tạo manifest chung cho toàn bộ ma trận.

Lệnh chạy chính thức:

```bat
python members\TV2\scripts\run_baseline_matrix.py ^
  --slots 500 ^
  --seeds 42 43 44 ^
  --output-root local_results\baseline_matrix
```

Kết quả:

```text
BASELINE MATRIX: 18/18 RUNS PASS
```

### 3.2. Script tổng hợp

`summarize_baseline_results.py` đọc 18 lần chạy và tạo:

```text
members/TV2/results/baseline_runs.csv
members/TV2/results/baseline_aggregate.csv
```

Lệnh tổng hợp:

```bat
python members\TV2\scripts\summarize_baseline_results.py ^
  --input-root local_results\baseline_matrix ^
  --output-dir members\TV2\results ^
  --expected-slots 500
```

Kết quả:

```text
BASELINE RUNS: 18 ROWS
BASELINE AGGREGATES: 6 ROWS
SUMMARY OUTPUT: PASS
```

## 4. Kiểm tra tính hợp lệ

Các điều kiện nghiệm thu đã đạt:

- `18/18` lần chạy hoàn thành.
- Mỗi lần chạy đủ `500` time slot.
- `18/18` run summary có trạng thái `complete`.
- `18/18` lần chạy có `conservation_ok = true`.
- `18/18` tệp `transitions.jsonl` có đúng `500` transition.
- `9/9` cặp cùng scenario và seed có cùng traffic đầu vào.
- Static luôn phân bổ `25/25 RB`.
- Queue-Based luôn sử dụng đủ `50 RB`.
- Queue-Based luôn cấp tối thiểu `5 RB` cho mỗi slice.
- Không có tổ hợp scenario, scheduler và seed bị trùng.
- Có đủ `18` dòng kết quả chi tiết và `6` dòng tổng hợp.

### 4.1. Kiểm tra traffic đầu vào

Các trường được đối chiếu gồm:

- `arrived_embb_bits`
- `arrived_urllc_bits`
- `offered_embb_mbps`
- `offered_urllc_mbps`

Kết quả:

```text
OFFICIAL COMMON INPUT: 9/9 PAIRS PASS
```

Do đó, khác biệt KPI phản ánh ảnh hưởng của chính sách phân bổ RB, không phải do khác traffic đầu vào.

### 4.2. Kiểm tra packet conservation

Packet conservation được kiểm tra theo:

```text
arrived = completed + dropped + unresolved_at_end
```

Tất cả 18 lần chạy đều đạt `conservation_ok = true`.

### 4.3. Kiểm tra phân bổ RB

Với Static:

```text
mean_embb_rb = 25
mean_urllc_rb = 25
min_embb_rb = max_embb_rb = 25
min_urllc_rb = max_urllc_rb = 25
```

Với Queue-Based:

```text
mean_embb_rb + mean_urllc_rb = 50
min_embb_rb >= 5
min_urllc_rb >= 5
```

## 5. Kết quả tổng hợp

Giá trị trung bình qua ba seed `42`, `43` và `44`:

| Scenario | Scheduler | eMBB throughput (Mbps) | URLLC throughput (Mbps) | URLLC completion rate | URLLC drop rate | Mean delay (ms) | Mean RB eMBB | Mean RB URLLC |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| stable_load | Static | 10.201256 | 3.663643 | 0.928010 | 0.071554 | 1.623657 | 25.000000 | 25.000000 |
| stable_load | Queue-Based | 14.657110 | 2.835295 | 0.614115 | 0.381038 | 3.298156 | 40.196667 | 9.803333 |
| urllc_burst | Static | 10.034249 | 3.694806 | 0.688174 | 0.308864 | 2.614067 | 25.000000 | 25.000000 |
| urllc_burst | Queue-Based | 12.395556 | 2.975187 | 0.517337 | 0.477317 | 3.109899 | 38.598667 | 11.401333 |
| poor_channel | Static | 3.139449 | 2.713085 | 0.591555 | 0.404952 | 3.191722 | 25.000000 | 25.000000 |
| poor_channel | Queue-Based | 5.506769 | 0.750093 | 0.030612 | 0.964541 | 4.758140 | 44.018667 | 5.981333 |

Xu hướng chung:

- Queue-Based tăng thông lượng eMBB trong cả ba scenario.
- Static bảo vệ URLLC tốt hơn trong cả ba scenario.
- Queue-Based làm completion rate giảm, drop rate và delay tăng.
- Mức suy giảm URLLC nghiêm trọng nhất trong `poor_channel`.

## 6. Phân tích kịch bản stable_load

### 6.1. Static Scheduler

Kết quả trung bình:

- eMBB throughput: `10.201256 Mbps`.
- URLLC throughput: `3.663643 Mbps`.
- URLLC completion rate: `92.80%`.
- URLLC drop rate: `7.16%`.
- Độ trễ trung bình: `1.623657 ms`.
- Phân bổ RB: `25/25`.

Phân bổ cố định giúp URLLC có tài nguyên ổn định, completion rate cao và delay thấp. Hạn chế là Static không phản ứng theo tải và không chuyển RB dư sang slice có nhu cầu cao hơn.

### 6.2. Queue-Based Scheduler

Kết quả trung bình:

- eMBB throughput: `14.657110 Mbps`.
- URLLC throughput: `2.835295 Mbps`.
- URLLC completion rate: `61.41%`.
- URLLC drop rate: `38.10%`.
- Độ trễ trung bình: `3.298156 ms`.
- RB trung bình: `40.196667/9.803333` cho eMBB/URLLC.

eMBB throughput tăng:

```text
14.657110 - 10.201256 = 4.455854 Mbps
```

Tương đương khoảng:

```text
4.455854 / 10.201256 × 100% ≈ 43.68%
```

Đổi lại, URLLC completion rate giảm mạnh, drop rate và delay tăng. Nguyên nhân là queue eMBB theo bit thường lớn hơn queue URLLC, khiến thuật toán thiên về eMBB.

## 7. Phân tích kịch bản urllc_burst

### 7.1. Static Scheduler

Kết quả trung bình:

- eMBB throughput: `10.034249 Mbps`.
- URLLC throughput: `3.694806 Mbps`.
- URLLC completion rate: `68.82%`.
- URLLC drop rate: `30.89%`.
- Độ trễ trung bình: `2.614067 ms`.
- Phân bổ RB: `25/25`.

So với `stable_load`, completion rate giảm và drop rate tăng. Điều này cho thấy `25 RB` chưa đủ xử lý hoàn toàn các đợt burst. Tuy vậy, Static vẫn bảo vệ URLLC tốt hơn Queue-Based.

### 7.2. Queue-Based Scheduler

Kết quả trung bình:

- eMBB throughput: `12.395556 Mbps`.
- URLLC throughput: `2.975187 Mbps`.
- URLLC completion rate: `51.73%`.
- URLLC drop rate: `47.73%`.
- Độ trễ trung bình: `3.109899 ms`.
- RB trung bình: `38.598667/11.401333` cho eMBB/URLLC.

Queue-Based tăng RB URLLC so với `stable_load`, chứng minh thuật toán có phản ứng với backlog URLLC. Tuy nhiên, phản ứng chưa đủ mạnh vì không xét tuổi gói và deadline.

## 8. Phân tích kịch bản poor_channel

### 8.1. Static Scheduler

Kết quả trung bình:

- eMBB throughput: `3.139449 Mbps`.
- URLLC throughput: `2.713085 Mbps`.
- URLLC completion rate: `59.16%`.
- URLLC drop rate: `40.50%`.
- Độ trễ trung bình: `3.191722 ms`.
- Phân bổ RB: `25/25`.

CQI thấp làm capacity trên mỗi RB giảm. Static vẫn duy trì 25 RB cho URLLC nên completion rate cao hơn Queue-Based, nhưng drop rate hơn 40% cho thấy phân bổ cố định cũng chưa đủ giải quyết kênh xấu.

### 8.2. Queue-Based Scheduler

Kết quả trung bình:

- eMBB throughput: `5.506769 Mbps`.
- URLLC throughput: `0.750093 Mbps`.
- URLLC completion rate: `3.06%`.
- URLLC drop rate: `96.45%`.
- Độ trễ trung bình: `4.758140 ms`.
- RB trung bình: `44.018667/5.981333` cho eMBB/URLLC.

Đây là hạn chế nghiêm trọng nhất. CQI thấp làm backlog eMBB tích lũy, khiến eMBB tiếp tục nhận phần lớn RB. URLLC chỉ nhận gần mức tối thiểu và hầu hết gói bị drop trước deadline.

## 9. So sánh tổng quát

### 9.1. Ưu điểm của Static Scheduler

- Đơn giản, dễ kiểm tra.
- Có tính xác định và tái lập.
- Luôn bảo đảm một nửa tài nguyên cho URLLC.
- Completion rate cao hơn Queue-Based.
- Drop rate và delay thấp hơn Queue-Based.
- Phù hợp làm baseline và fallback an toàn.

### 9.2. Hạn chế của Static Scheduler

- Không thích ứng theo tải.
- Không sử dụng backlog, CQI, deadline hoặc độ trễ gói.
- Có thể cấp thừa RB cho slice ít nhu cầu.
- eMBB throughput thấp hơn Queue-Based.
- Không tăng tài nguyên URLLC khi burst xuất hiện.

### 9.3. Ưu điểm của Queue-Based Scheduler

- Thích ứng theo backlog.
- Tăng eMBB throughput trong cả ba scenario.
- Luôn sử dụng đủ 50 RB.
- Bảo đảm tối thiểu 5 RB cho mỗi slice.
- Có tính xác định và tái lập.
- Có phản ứng nhất định với burst URLLC.

### 9.4. Hạn chế của Queue-Based Scheduler

- Chỉ sử dụng `queue_bits`.
- Không xét deadline, độ trễ gói cũ nhất hoặc CQI.
- Queue eMBB theo bit thường lớn hơn queue URLLC.
- Có thể duy trì trạng thái gần `45/5 RB` lâu dài.
- Mức tối thiểu 5 RB không đủ bảo vệ URLLC.
- URLLC drop rate đặc biệt cao trong `poor_channel`.

## 10. So sánh sự đánh đổi eMBB và URLLC

Trong `stable_load`:

- eMBB throughput tăng khoảng `43.68%` với Queue-Based.
- URLLC completion rate giảm từ `92.80%` xuống `61.41%`.
- URLLC drop rate tăng từ `7.16%` lên `38.10%`.

Trong `urllc_burst`:

- eMBB throughput tăng.
- URLLC completion rate giảm từ `68.82%` xuống `51.73%`.
- URLLC drop rate tăng từ `30.89%` lên `47.73%`.

Trong `poor_channel`:

- eMBB throughput tăng từ khoảng `3.14 Mbps` lên `5.51 Mbps`.
- URLLC completion rate giảm từ `59.16%` xuống `3.06%`.
- URLLC drop rate tăng từ `40.50%` lên `96.45%`.

Mức đánh đổi trong `poor_channel` là quá lớn. Việc tăng eMBB throughput không bù được việc gần như toàn bộ gói URLLC bị drop.

## 11. Ý nghĩa đối với thiết kế QoS-Weighted Heuristic

QoS-Weighted Heuristic cần sử dụng:

```text
embb.queue_bits
embb.cqi
urllc.queue_bits
urllc.cqi
urllc.oldest_packet_delay_ms
urllc.deadline_ms
```

Thuật toán mới cần:

1. Tổng phân bổ luôn bằng `50 RB`.
2. Không có RB âm.
3. Có mức tài nguyên tối thiểu cho mỗi slice.
4. Tăng ưu tiên URLLC khi gói cũ nhất gần deadline.
5. Không để URLLC ở mức tối thiểu quá lâu.
6. Xét CQI để đánh giá hiệu quả RB.
7. Cho phép eMBB dùng tài nguyên dư khi URLLC không có nhu cầu.
8. Có tính xác định và tái lập.
9. Tạo Action đúng Contract `1.0.0`.
10. Hoạt động với runner, registry và RAN Simulator hiện tại.
11. Có unit test cho deadline, CQI và các trường hợp biên.

QoS Heuristic không nên chỉ tăng cố định minimum RB của URLLC. Trọng số phải được đánh giá trên cả ba scenario và nhiều seed.

## 12. Hạn chế của benchmark

- Chỉ sử dụng ba seed: `42`, `43`, `44`.
- Mỗi lần chạy gồm `500` slot.
- Chỉ đánh giá Static và Queue-Based.
- Chưa có QoS-Weighted Heuristic.
- Chưa có DQN trong cùng bảng so sánh.
- Chưa ghép RAN KPI với Core KPI SRv6.
- Chưa đánh giá timeout và fallback của Orchestrator.
- Chưa đánh giá thời gian tính toán Action.
- Kết quả phụ thuộc mô hình traffic, CQI, capacity và deadline hiện tại của TV1.

Baseline được dùng để xác định xu hướng và yêu cầu thiết kế, chưa phải kết luận cuối cùng của toàn hệ thống.

## 13. Đầu ra của benchmark

Các sản phẩm được tạo:

```text
members/TV2/scripts/run_baseline_matrix.py
members/TV2/scripts/summarize_baseline_results.py
members/TV2/results/baseline_runs.csv
members/TV2/results/baseline_aggregate.csv
members/TV2/results/baseline_analysis.md
```

- `run_baseline_matrix.py`: chạy và kiểm tra 18 tổ hợp.
- `summarize_baseline_results.py`: kiểm tra, tổng hợp và xuất CSV.
- `baseline_runs.csv`: 18 dòng kết quả chi tiết.
- `baseline_aggregate.csv`: 6 dòng thống kê theo scenario và scheduler.
- `baseline_analysis.md`: phân tích kỹ thuật và yêu cầu cho QoS.

Dữ liệu thô nằm tại:

```text
local_results/baseline_matrix
```

Thư mục `local_results` không được commit vì dữ liệu có thể tái tạo bằng script và log thô không phải mã nguồn bàn giao.

## 14. Hướng phát triển tiếp theo

Sau khi baseline được review và merge:

1. Tạo nhánh `feature/tv2-qos-heuristic` từ `origin/main`.
2. Thiết kế QoS score dựa trên backlog, urgency và CQI.
3. Review thiết kế với TV1 và TV5.
4. Triển khai `qos_heuristic.py`.
5. Thêm cấu hình và đăng ký scheduler.
6. Viết unit test.
7. Chạy smoke test 10 slot.
8. Chạy benchmark 500 slot.
9. Chạy đủ ba scenario và ba seed.
10. So sánh Static, Queue-Based và QoS.
11. Bàn giao QoS cho Orchestrator.
12. Phối hợp với TV3 để so sánh DQN.
13. Phối hợp với TV4 và TV5 trong tích hợp đầu cuối.

Tiêu chí cải thiện chính của QoS:

- Completion rate URLLC cao hơn Queue-Based.
- Drop rate và delay URLLC thấp hơn Queue-Based.
- Không làm eMBB throughput giảm quá mức.
- Cải thiện rõ trong `urllc_burst` và `poor_channel`.
- Không vi phạm Contract và tổng RB.

## 15. Kết luận

Benchmark 18 lần chạy chứng minh Static và Queue-Based đều đáp ứng Contract, tổng RB, packet conservation và khả năng tái lập.

Static bảo vệ URLLC tốt hơn trong cả ba scenario, nhưng không thích ứng theo tải và có eMBB throughput thấp hơn.

Queue-Based tăng eMBB throughput nhờ phân bổ theo backlog, nhưng việc chỉ dùng `queue_bits` khiến thuật toán thiên mạnh về eMBB và làm giảm đáng kể chất lượng URLLC.

Hạn chế nghiêm trọng nhất xuất hiện trong `poor_channel`:

```text
URLLC completion rate ≈ 3.06%
URLLC drop rate ≈ 96.45%
Mean URLLC delay ≈ 4.76 ms
Mean URLLC RB ≈ 5.98 RB
```

Kết quả cho thấy mức tối thiểu `5 RB` không đủ bảo vệ URLLC khi CQI thấp, capacity giảm, backlog eMBB lớn và gói URLLC gần deadline.

Baseline cung cấp cơ sở thực nghiệm rõ ràng cho QoS-Weighted Heuristic. Thuật toán tiếp theo cần kết hợp backlog, deadline urgency, độ trễ gói cũ nhất, CQI và khả năng sử dụng tài nguyên dư.

Mục tiêu cuối là cân bằng tốt hơn giữa:

- Thông lượng eMBB.
- Độ trễ URLLC.
- URLLC completion rate.
- URLLC drop rate.
- Hiệu quả sử dụng RB.

QoS-Weighted Heuristic phải duy trì tính xác định, khả năng tái lập và tương thích với Contract, runner, RAN Simulator và Orchestrator hiện tại.
