# NSL Lab web — hướng dẫn bàn giao TV4

## Kiến trúc và trạng thái số liệu

- Chạy web trên Windows từ **thư mục gốc repo**. Nó gọi mã TV1/TV2/TV3 trực tiếp và lưu kết quả vào `web_data/<run_id>/`.
- Controller mở rộng `members/TV4/controller/tv4_web_agent.py` chạy **trong GNS3 VM**, cùng thư mục với bốn module TV4 hiện có. Windows kết nối qua SSH tunnel `127.0.0.1:18018 → VM:127.0.0.1:8018`.
- Một lô RAN gồm 4 thuật toán × 3 seed cùng cấu hình. Core đo normal trước thay đổi, đo lại trong kịch bản, rồi khôi phục và đo lần nữa. ICMP RTT, TCP/UDP được đo tuần tự cho hai slice. **Không phải phép đo gói tin End-to-End qua RAN và Core cùng lúc.** Core KPI chung cho lô, không gán thành KPI riêng từng thuật toán.
- API `/core-kpi` cũ là dữ liệu lịch sử, web không đưa vào kết quả một lượt chạy mới. `switching_time_ms` chưa được đo. Khi không đo Core được, lượt chạy báo lỗi và lưu log.
- DQN dùng checkpoint `members/TV3/models/dqn_v2_best.zip`. Thay đổi RB/tải/CQI/deadline so với huấn luyện là phép thử ngoại suy, không phải kết quả chuẩn của checkpoint.

## Cài đặt trên GNS3 VM (TV4)

Từ thư mục gốc repo đã chuyển sang VM, dùng Python 3.10+ và môi trường Flask hiện tại:

```bash
python3 -m pip install -r members/TV4/controller/requirements.txt
cd members/TV4/controller
export NSL_ENABLE_LAB_APPLY=1
python3 tv4_web_agent.py
```

Agent chỉ lắng nghe `127.0.0.1:8018`. Máy VM cần `sudo -n docker`, các node GNS3 Client/R1/R2/R3/R4/Server đang chạy, `tc` trên R2/R3 `eth1`, ping và iperf3 server trên `2001:db8:40::2:5201`. Cần xác nhận mapping container/interface thực tế trước khi áp kịch bản. Tránh chạy đồng thời controller `tv4_core_controller_unified.py` trên cùng cổng 8018; agent này đã import controller hợp nhất.
Nếu chưa sẵn sàng thay đổi lab, bỏ `export NSL_ENABLE_LAB_APPLY=1` và chọn chế độ RAN-only trên web. Lúc đó API kịch bản Core trả HTTP 403.

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
- `GET /api/runs/{id}/download`: ZIP gồm cấu hình và manifest mỗi seed, `slots.csv`, `trace.jsonl` (State/Action/Transition), `summary.json`, `comparison.csv`, `report.html` (bảng và biểu đồ mở ngoại tuyến), `job.json` (phản hồi Core trước–sau–khôi phục và dữ liệu ping/iperf3 thô).
- Máy VM: `POST /v1/lab/scenario` và `POST /v1/lab/measure` bổ sung trên controller cổng 8018. Các endpoint TV4 cũ vẫn hoạt động.

Mỗi slot lưu `request_id`, CQI, queue, action/RB và KPI. Tỷ lệ rớt gói ở bảng so sánh lấy từ tổng gói của mỗi seed. Các kết quả chạy thiếu slot phải được gắn là thử nghiệm ngắn, không dùng để so sánh chính thức với lượt 500 slot.

## Giới hạn so với mục 2.5.2 và 4.5 của báo cáo

Web giữ nguyên bộ đánh giá batch, đồng thời thêm `members/TV5/orchestrator_web.py` và các nút TV5 tạo session, State, Decision, Step, chạy hết, tải CSV/log. Module TV5 mới dùng State/Action/KPI thật của TV1, scheduler Static/Queue/QoS thật của TV2 và checkpoint DQN của TV3. Đây là phiên bản tích hợp web theo hợp đồng TV5, **không phải API V2 cũ** trong `members/TV5/TV5/` (bản đó thiếu QoS và đường import không khớp thư mục hiện tại). Session đang chạy được lưu trong RAM; sau khi web khởi động lại, session đã hoàn thành vẫn hiện trong lịch sử và tải lại được, nhưng không thể tiếp tục session dở dang.

API: `POST /api/tv5/sessions` nhận `{experiment: <đối tượng POST /api/runs>, algorithm, seed, fallback, inject_dqn_failure}`; `GET /api/tv5/sessions/{id}/state`, `POST /decision`, `POST /step`, `POST /run-to-end`, `GET /metrics`, `GET /download`. Decision lặp lại trong cùng slot trả Action cũ, không áp dụng lên TV1; Step ghi request ID, thuật toán yêu cầu/thực tế và lý do fallback. Chế độ tiêm lỗi DQN là **thử nghiệm lỗi có chủ đích**; kết quả sau fallback phải gắn nhãn QoS/Static thực tế, không tính thành kết quả DQN chuẩn. Khi DQN không load được và bật fallback, luồng chuyển QoS rồi Static; tắt fallback sẽ báo lỗi.

Nút **Chạy bộ kịch bản** dùng `POST /api/suites`, `GET /api/suites/{id}` để chạy tuần tự các cặp RAN/Core đã chọn. Mặc định ba RAN × Core normal × bốn thuật toán × ba seed = 36 lượt RAN. Nếu chọn cả năm Core, số lượt và thời gian đo tăng gấp năm; mỗi cặp có run ID và ZIP riêng. Với Core live, web áp và khôi phục topology cho từng cặp. Các kịch bản RAN khác kịch bản hiện chọn lấy tải/CQI/burst từ YAML của TV1, còn slot/RB/deadline từ form.

Trước khi chạy, bấm **Kiểm tra sẵn sàng** (`GET /api/readiness`) để xem file thiếu và tình trạng lab agent. Cần xác nhận trên VM: đúng tên container GNS3.Client/R1/R2/R3/Server, `eth1` R2/R3, địa chỉ nguồn/đích, quyền `sudo -n docker`, `tc`, ping, iperf3 và iperf3 server. Endpoint health chỉ kiểm tra một phần topology; một phép đo thật thành công cùng log readback mới chứng minh kịch bản Core chạy. DQN phải cài đủ torch/SB3 và checkpoint tải được trên Windows.

**Giới hạn còn lại:** TV5 web và Core đo theo cửa sổ riêng, không chứng minh độ trễ cùng một gói RAN→Core. Core policy là ánh xạ slice cố định, chưa có bộ tối ưu policy động theo KPI hoặc đo switching time. Module TV5 web chưa ghi tiếp session qua lần khởi động lại hoặc kiểm thử nhiều client đồng thời. Báo cáo thực hành phải kèm log gốc, Git commit, ảnh/topology GNS3, bằng chứng policy/qdisc trước–sau và kết quả đo thật của cả năm kịch bản Core trước khi khẳng định MC-07/08/09 hoàn tất.
