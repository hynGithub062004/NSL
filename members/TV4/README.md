# TV4 — Core Network SRv6

## 1. Giới thiệu

TV4 phụ trách mô phỏng Core Network sử dụng Segment Routing over IPv6 (SRv6), điều khiển SR Policy bằng REST API và đánh giá các chỉ số QoS/KPI trong đồ án **“Tối ưu hóa End-to-End cho Network Slicing: Kết hợp cấp phát Resource Block trong OFDMA và Segment Routing”**.

## 2. Mô hình mạng

Topology GNS3 có 6 node: `Client — R1 — R2/R3 — R4 — Server`.

| Slice | IPv6 nguồn | Bảng định tuyến R1 | Chính sách mặc định | Đường đi |
|---|---|---:|---|---|
| eMBB | `2001:db8:10::2` | 100 | `high_bandwidth` | R1 → R2 → R4 → Server |
| URLLC | `2001:db8:10::3` | 101 | `low_latency` | R1 → R3 → R4 → Server |

Mạng Server: `2001:db8:40::/64`. Hai bảng định tuyến được phân biệt bằng quy tắc định tuyến IPv6 theo địa chỉ nguồn.

## 3. Cấu trúc thư mục

- `controller/`: mã nguồn Core Controller và REST API.
- `benchmarks/`: chương trình đo RTT và lưu lượng TCP/UDP.
- `scripts/`: script cấu hình SRv6, khôi phục cơ bản, QoS và định tuyến hai slice.
- `results/`: CSV tổng hợp và kết quả từng lượt benchmark.
- `gns3/`: bản sao lưu project GNS3.
- `docs/`: hướng dẫn tích hợp TV5 và ví dụ phản hồi API.

## 4. Core Controller và API

Controller hợp nhất sử dụng Flask, chạy trong GNS3 VM và lắng nghe trên `127.0.0.1:8018`. Có thể kết nối từ chính máy Windows tạo SSH Tunnel qua `127.0.0.1:18018`.

| Phương thức | Endpoint | Chức năng |
|---|---|---|
| GET | `/health` | Trạng thái Controller |
| GET | `/policies` | Trạng thái policy trên R1 |
| POST | `/apply-policy` | Xem trước hoặc áp dụng thay đổi SR Policy |
| GET | `/core-kpi?slice_id=embb` | KPI eMBB từ benchmark đã lưu |
| GET | `/core-kpi?slice_id=urllc` | KPI URLLC từ benchmark đã lưu |
| GET | `/v1/events` | Sự kiện áp dụng policy được ghi nhận |

Ví dụ yêu cầu **xem trước**, không thay đổi mạng:

```json
{
  "request_id": "tv5-preview-example-001",
  "slice_id": "embb",
  "policy": "low_latency"
}
```

Việc áp dụng policy thật yêu cầu bổ sung trường `"confirm": "APPLY_TV4"` và sử dụng `request_id` mới cho hành động mới. Chỉ thực hiện trong môi trường thử nghiệm đã được xác nhận an toàn. Phần rollback đã được kiểm thử bằng lỗi **giả lập**, không tương đương kiểm thử đứt đường truyền thực tế.

**Giới hạn:** API Core KPI hiện trả về **dữ liệu benchmark lịch sử** (`measurement.is_live = false`), không phải số đo thời gian thực. `packet_loss` là tỷ lệ dạng fraction (nhân 100 để ra phần trăm). `switching_time_ms` chưa đo, giá trị `null`.

## 5. Cấu hình QoS dùng khi benchmark

| Tham số trên `eth1` | R2 (eMBB) | R3 (URLLC) |
|---|---|---|
| Delay | 5 ms | 1 ms |
| Loss cấu hình | 0,1% | 0,01% |
| Rate | 100 Mbit/s | 30 Mbit/s |
| Queue limit | 1000 packets | 1000 packets |

Đây là **tham số cấu hình**, không phải KPI đo được; không suy ra SLA thực tế chỉ từ các giá trị trên.

## 6. Kết quả benchmark lịch sử

Các kết quả dưới đây đến từ các lượt đo **tuần tự**, không phải tải đồng thời hai slice:

| Chỉ số | eMBB | URLLC |
|---|---:|---:|
| RTT trung bình | 7,5146 ms | 3,3884 ms |
| TCP throughput trung bình | 57,32716 Mbps | 26,30012 Mbps |

Dữ liệu chi tiết của từng lượt đo và số liệu tổng hợp nằm trong `results/`. Không sử dụng các kết quả lịch sử như KPI trực tiếp của một policy mới vừa chuyển.

## 7. Trạng thái kiểm thử

**Đã thực hiện:** xây dựng topology và SRv6; phân luồng hai slice; đo RTT, TCP/UDP, jitter và packet loss; kiểm tra các endpoint Core Controller; thử cơ chế idempotency và xử lý lỗi API; rollback giả lập; đối chiếu SHA256 của bốn file Controller chính với bản GNS3 VM; kiểm tra cú pháp 14 script bằng `bash -n`.

**Chưa hoàn thành:** chạy thử quy trình khôi phục đầy đủ bằng các script mới; kiểm thử sự cố đường truyền thực tế; tích hợp trực tiếp Orchestrator TV5; đánh giá End-to-End hoàn chỉnh.

## 8. Hướng dẫn tái tạo và lưu ý

- Project `.gns3project` không bảo đảm chứa Docker image `gns3-srv6:1.0` hoặc cấu hình runtime đã thay đổi trong container.
- Bản `.gns3project` đã bao gồm một số cấu hình khởi động `/etc/network/interfaces` cho 6 node, trong đó R1 có quy tắc nguồn/đích với ưu tiên `1000/1001`, R2/R3 có cấu hình `tc netem`. Khả năng áp dụng tự động phụ thuộc cách GNS3 gắn các file này vào Docker image tương thích. Script `13_r1_dual_slice.sh` đã được điều chỉnh để nhận diện các rule này và không tạo bản trùng khi rule phù hợp đã tồn tại.
- Bộ script cấu hình SRv6 ban đầu và các script QoS/dual-slice bổ sung **chưa được tích hợp thành một quy trình khôi phục tự động đã kiểm thử toàn diện**.
- Trước khi chạy script cần kiểm tra Docker image, ánh xạ container/node, giao diện `eth*`, các tuyến IPv6, quy tắc `ip -6 rule` và độ ưu tiên rule.
- Script `restore_from_gns3_vm.sh` ban đầu chỉ phục hồi cấu hình nền; không tự động bảo đảm hai slice và QoS mới được dựng đủ.
- Tránh đưa mật khẩu, token, khóa SSH, môi trường `.venv`, file ledger sự kiện có thông tin riêng hoặc dữ liệu tạm lên repository công khai.

Tài liệu giao tiếp TV4 ↔ TV5 nằm tại `docs/README_TV5.md`.

**Phụ thuộc để tái tạo**: Python ≥ 3.10 và Flask 3.1.3 cho Controller; GNS3 VM, Docker image tùy chỉnh `gns3-srv6:1.0`, `iproute2` (bao gồm `ip`, `tc`), công cụ `ping`, `iperf3`, SSH và quyền thực hiện lệnh `sudo -n docker` khi dùng Controller. Mã nguồn xây dựng Docker image và tự động dựng toàn bộ môi trường hiện **chưa** được đưa vào gói này. Kết quả `results/` tham chiếu log trên GNS3 VM, nhưng log gốc không nằm trong gói nộp.
