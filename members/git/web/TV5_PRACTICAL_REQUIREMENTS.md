# Yêu cầu để hoàn thành phần thực hành TV5

## Mã đã có trong gói

| Hạng mục | Đường dẫn | Tình trạng |
|---|---|---|
| Mô phỏng RAN và ba cấu hình | `members/TV1/src/ran/`, `members/TV1/configs/*.yaml` | Có trong repo |
| Static, Queue-based, QoS Heuristic | `members/TV2/src/schedulers/` | Có trong repo |
| DQN và checkpoint | `members/TV3/dqn_scheduler.py`, `members/TV3/models/dqn_v2_best.zip` | Có file; cần kiểm tra tải model trên Windows |
| TV4 controller và agent đo live | `members/TV4/controller/tv4_core_controller_unified.py`, `tv4_web_agent.py` | Có file; cần chạy trên GNS3 VM |
| TV5 điều phối theo slot | `members/TV5/orchestrator_web.py` | Có trong gói cập nhật |
| Web, batch, suite và export | `web/` | Có trong gói cập nhật |

## Thông tin phải kiểm tra trên máy TV4 trước khi gọi kết quả là phép đo thật

1. Windows dùng Python 3.11, đủ gói trong `web/requirements.txt`; `python -c "from members.TV3.dqn_scheduler import DQNScheduler"` và load checkpoint thành công.
2. GNS3 VM chạy topology TV4; container tên `GNS3.Client.*`, `GNS3.R1.*`, `GNS3.R2.*`, `GNS3.R3.*`, `GNS3.R4.*`, `GNS3.Server.*`; R2/R3 dùng `eth1` đúng đường tác động. Nếu tên/interface khác, cần sửa mapping trong `tv4_web_agent.py` theo topology thật.
3. VM cho phép `sudo -n docker`; Client có ping/iperf3 và IP nguồn `2001:db8:10::2` (eMBB), `2001:db8:10::3` (URLLC); Server có `2001:db8:40::2`, iperf3 lắng nghe cổng 5201. Địa chỉ khác thì cập nhật `SOURCES`, `TARGET`.
4. Agent chạy với `NSL_ENABLE_LAB_APPLY=1` trên VM; Windows mở tunnel `127.0.0.1:18018` đến VM `127.0.0.1:8018`. Không chạy đồng thời controller cũ trên cùng cổng.
5. Sau khi bấm **Kiểm tra sẵn sàng**, chạy lần ngắn từng kịch bản Core, xác minh `job.json`: qdisc và policy readback, thời điểm đo, raw ping/iperf3, khôi phục normal. Lưu ảnh topology và log gốc.

## Ma trận thực hành trên web

| Bài thử | Thao tác | Bằng chứng |
|---|---|---|
| TV5 State → Decision → Step | Tạo session, xem State, Decision hai lần, Step một lần | Cùng request ID trong slot; Decision không đổi State; log Action và KPI |
| TV5 fallback | DQN + tiêm lỗi + bật fallback | `selected_scheduler=qos_heuristic`, `fallback_reason`, `fallback_count` trong CSV/log |
| So sánh RAN | Bộ ba RAN, bốn thuật toán, seed 42/43/44, 500 slot | 36 run RAN, CSV từng slot, bảng/biểu đồ và manifest; kiểm tra bảo toàn RB/gói |
| Core SRv6 | Normal, delay, outage, loss, recovery lần lượt | KPI ping/TCP/UDP, policy/qdisc trước–sau, nhật ký và khôi phục |
| Thử lỗi tích hợp | Tắt tunnel hoặc checkpoint lỗi trong bài thử riêng | Lỗi được hiển thị, không gán KPI Core lịch sử thành phép đo live, không gán fallback thành DQN |

## Phạm vi chưa có bằng chứng thực nghiệm từ môi trường này

- Chưa truy cập được GNS3 VM của bạn để chứng minh năm kịch bản Core chạy thật. Mã kiểm thử Core trong `web/test_web.py` dùng mock; ảnh một lượt normal trước đây không chứng minh đủ năm kịch bản.
- Chưa có tuyến gói tin chung xuyên TV1 RAN simulator và TV4 GNS3, nên không được công bố trễ hay loss End-to-End cùng gói.
- TV4 chưa cung cấp phép đo chuyển tuyến có mốc thời gian đáng tin cậy (`switching_time_ms`) hay lưu lượng đồng thời hai slice. Nếu mục này là chỉ tiêu bắt buộc trong báo cáo, cần thêm probe và timestamp trực tiếp tại các node TV4, rồi mới nối vào web.
- Session TV5 đang chạy lưu trong RAM một tiến trình; nếu tắt web giữa chừng phải tạo lượt mới. Bản API V2 cũ dưới `members/TV5/TV5/` vẫn là mẫu cũ và chưa tự được thay thế bởi API web này.
