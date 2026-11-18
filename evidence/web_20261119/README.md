# Minh chứng Web NSL — kiểm thử 18/11/2026

Tám ZIP gốc đã được kiểm tra CRC và tính hợp lệ của số lượt/slot/cấp phát RB. Không bao gồm các lượt thử cấu hình sai hoặc suite 0/3.

## RAN (chỉ mô phỏng)

| Kịch bản | Run ID | Lượt × slot | File |
|---|---|---:|---|
| Stable Load | d803bcd43b2647ab | 12 × 500 | RAN/NSL_d803bcd43b2647ab.zip |
| URLLC Burst | 2d377a26233a4d38 | 12 × 500 | RAN/NSL_2d377a26233a4d38.zip |
| Poor Channel | 4f5f9ec53c6f4000 | 12 × 500 | RAN/NSL_4f5f9ec53c6f4000.zip |

Ba seed: 42, 43, 44; bốn thuật toán: Static, Queue-based, QoS Heuristic, DQN; 500 slot/lượt, 50 RB. Tổng 36 lượt, 18.000 slot.

| Kịch bản | DQN thông lượng eMBB (Mbps) | DQN trễ URLLC (ms) | DQN tỷ lệ rớt URLLC |
|---|---:|---:|---:|
| Stable Load | 12.385527 | 1.456905 | 1.8747% |
| URLLC Burst | 11.140505 | 1.418923 | 21.2313% |
| Poor Channel | 1.589417 | 1.778722 | 21.1286% |

## Core trên GNS3 VM (ping/iperf3 trực tiếp, RAN chạy riêng)

| Kịch bản | Run ID | File |
|---|---|---|
| Normal | e511b718aaed470d | Core/NSL_e511b718aaed470d.zip |
| Delay | b703fa6c37b34cab | Core/NSL_b703fa6c37b34cab.zip |
| Loss | ca14be42e89740b5 | Core/NSL_ca14be42e89740b5.zip |
| Outage | 0348b7daa71c4df4 | Core/NSL_0348b7daa71c4df4.zip |
| Recovery | d8abd7f007234672 | Core/NSL_d8abd7f007234672.zip |

Năm lượt Core đều hoàn thành, đo mới trực tiếp (`measurement.is_live=true`) và có policy readback sau khôi phục. Normal: một phép đo; các kịch bản còn lại: trước, trong, sau. Dữ liệu Core dùng Static, seed 42, 10 slot, 50 RB để kiểm tra tích hợp Web.

## Phạm vi và giới hạn

- RAN được mô phỏng và Core được đo trực tiếp **theo hai phép thử độc lập**; không chứng minh RTT hay thông lượng End-to-End cùng một gói tin.
- Outage là cấu hình loss 100% trên R2 và chuyển policy eMBB có điều khiển; không chứng minh tự phát hiện sự cố hay thời gian switching.
- Recovery riêng chạy khi hệ thống đã ở Normal; không phải phép đo thời gian hồi phục sau hỏng hóc đang diễn ra.
- Các ZIP mô tả scheduler là `dqn`, không lưu hash checkpoint; ghi nhận v3 dựa trên bản Web đã dùng tại thời điểm chạy.
- `job.json` lưu `burst_multiplier=6` cho một số kịch bản không dùng burst; `config.json` thực thi mới là cấu hình chính xác (ở Stable Load/Poor Channel: 1).

Đối chiếu file gốc bằng `SHA256SUMS.txt` hoặc `manifest.json`. Không thêm toàn bộ `web_data/` vào Git.
