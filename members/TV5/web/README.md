# NSL Lab web — hướng dẫn bàn giao TV4

## Kiến trúc và trạng thái số liệu

- Chạy web trên Windows từ **thư mục gốc repo**. Nó gọi mã TV1/TV2/TV3 trực tiếp và lưu kết quả vào `web_data/<run_id>/`.
- Controller mở rộng `members/TV4/controller/tv4_web_agent.py` chạy **trong GNS3 VM**, cùng thư mục với bốn module TV4 hiện có. Windows kết nối qua SSH tunnel `127.0.0.1:18018 → VM:127.0.0.1:8018`.
- Một lô RAN gồm 4 thuật toán × 3 seed cùng cấu hình. Core áp policy/kịch bản một lần, rồi đo ICMP RTT, TCP/UDP lần lượt cho hai slice sau các lượt RAN. **Không phải phép đo gói tin End-to-End qua RAN và Core cùng lúc.** Core KPI chung cho lô, không gán thành KPI riêng từng thuật toán.
- API `/core-kpi` cũ là dữ liệu lịch sử, web không đưa vào kết quả một lượt chạy mới. `switching_time_ms` chưa được đo. Khi không đo Core được, lượt chạy báo lỗi và lưu log.
- DQN dùng checkpoint `members/TV3/models/dqn_v2_best.zip`. Thay đổi RB/tải/CQI/deadline so với huấn luyện là phép thử ngoại suy, không phải kết quả chuẩn của checkpoint.

## Cài đặt trên GNS3 VM (TV4)

Từ thư mục gốc repo đã chuyển sang VM, dùng Python 3.10+ và môi trường Flask hiện tại:

```bash
python3 -m pip install -r members/TV4/controller/requirements.txt
cd members/TV4/controller
python3 tv4_web_agent.py
```

Agent chỉ lắng nghe `127.0.0.1:8018`. Máy VM cần `sudo -n docker`, các node GNS3 Client/R1/R2/R3/R4/Server đang chạy, `tc` trên R2/R3 `eth1`, ping và iperf3 server trên `2001:db8:40::2:5201`. Cần xác nhận mapping container/interface thực tế trước khi áp kịch bản. Tránh chạy đồng thời controller `tv4_core_controller_unified.py` trên cùng cổng 8018; agent này đã import controller hợp nhất.

## Cài đặt trên Windows (máy chạy web)

Clone `main` hoặc giải nén gói mã hoàn chỉnh; dùng Python 3.11 trên Windows. Trong PowerShell, mở cửa sổ tunnel:

```powershell
ssh -N -L 18018:127.0.0.1:8018 gns3@GNS3_VM_IP
```

Ở PowerShell thứ hai, từ thư mục repo:

```powershell
PowerShell -ExecutionPolicy Bypass -File .\web\start_windows.ps1 -Gns3VmIp GNS3_VM_IP
```

Mở `http://127.0.0.1:8080`. Trước khi chạy, kiểm tra `/api/health` và `http://127.0.0.1:18018/v1/lab/health`. Nếu chưa có VM, chọn **Chỉ kiểm thử RAN** trên form; kết quả Core sẽ để trống.

## Kịch bản Core

| Tên | Thay đổi trên VM | Sau lượt chạy |
|---|---|---|
| `normal` | R2 5 ms/0,1%/100 Mbit; R3 1 ms/0,01%/30 Mbit; policy mặc định | Giữ mặc định |
| `delay` | R2 thêm trễ 35 ms | Phục hồi mặc định |
| `loss` | R2 mất 10%, R3 mất 2% | Phục hồi mặc định |
| `outage` | R2 mất 100%, chuyển eMBB qua R3 | Phục hồi mặc định |
| `recovery` | Khôi phục qdisc và hai policy mặc định | Giữ mặc định |

Những thao tác này thay qdisc `root` của `eth1` trên R2/R3; sử dụng **chỉ trong topology lab**. Nếu bước khôi phục lỗi, web hiển thị cảnh báo phải khôi phục thủ công. Core đo tuần tự, vì vậy không suy ra cách ly hai slice dưới tải đồng thời.

## API và tệp xuất

- `POST /api/runs`: khởi động batch không đồng bộ; chỉ một batch tại một thời điểm vì Core là tài nguyên dùng chung.
- `GET /api/runs`, `GET /api/runs/{id}`: xem tiến độ, dữ liệu đã lưu và so sánh.
- `GET /api/runs/{id}/download`: ZIP gồm cấu hình mỗi seed, `slots.csv`, `summary.json`, `comparison.csv`, `report.html` (bảng và biểu đồ mở ngoại tuyến), `job.json` và nhật ký kịch bản Core.
- Máy VM: `POST /v1/lab/scenario` và `POST /v1/lab/measure` bổ sung trên controller cổng 8018. Các endpoint TV4 cũ vẫn hoạt động.

Mỗi slot lưu `request_id`, CQI, queue, action/RB và KPI. Tỷ lệ rớt gói ở bảng so sánh lấy từ tổng gói của mỗi seed. Các kết quả chạy thiếu slot phải được gắn là thử nghiệm ngắn, không dùng để so sánh chính thức với lượt 500 slot.
