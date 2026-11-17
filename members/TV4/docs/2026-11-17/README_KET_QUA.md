# TV4 — Bổ sung kết quả Core SRv6 ngày 17/11/2026

## Nội dung

- `../../controller/tv4_web_agent.py`: bản mã Core Agent lấy từ bản sao lưu GNS3 ngày 17/11/2026. **Phải đối chiếu SHA-256 với file đang chạy trên GNS3 VM trước khi coi là phiên bản chạy cuối cùng**.
- `../../gns3/Network_Slicing_SRv6_20261117.gns3`: topology 6 node trong backup ngày 17/11; **không chứa toàn bộ Docker image hoặc cấu hình runtime**.
- `../../results/2026-11-17/`: 5 gói ZIP nguyên bản Normal, Delay, Loss, Outage, Recovery (mỗi bộ 500 slot, các seed 42/43/44 và 4 thuật toán RAN) cùng 1 gói smoke test Static/42/10-slot sau reboot. Các bộ có thể tự chứa kết quả RAN, Core nhưng **Core được đo độc lập tuần tự, không phải phép đo E2E RAN–Core**.
- Các file Word: phân tích Bước 16, biên bản nghiệm thu và hướng dẫn vận hành.

## Giới hạn quan trọng

- Bản GNS3 đầy đủ kèm Docker image và cấu hình lưu trong bản bàn giao ngoại tuyến `NSL_BAN_GIAO_HOAN_CHINH_20261117.zip` (~41 MiB). Không tải bản này vào `main`; giữ bản gốc và chia sẻ qua OneDrive/USB sau khi rà soát thông tin nhạy cảm.
- Chưa thử phục hồi trọn vẹn bản sao trên máy sạch.
- Chưa đo thời gian chuyển tuyến, lưu lượng hai slice đồng thời hay độ trễ End-to-End đi qua cả RAN/Core.
- Core Agent trên VM có thể thay đổi sau lúc chụp backup: hãy lấy bản đang chạy từ `/home/gns3/TV4_Core_Controller/tv4_web_agent.py` trước khi commit nếu mã nguồn khác nhau.
- Giao diện Web chạy trên Windows là phần tích hợp; **chưa đồng bộ từ máy Windows vào lần cập nhật TV4 này**. Phối hợp TV5 trước khi thay đổi thư mục `web/` ở gốc repo.
- Biên bản nghiệm thu ở dạng **dự thảo chưa ký**.

## Trình diễn nhanh

1. Khởi động GNS3 VM và mở project hiện tại trong GNS3. Start 6 node.
2. Kiểm tra trên VM: `systemctl is-active tv4-core-agent.service` (kỳ vọng `active`).
3. Trên Windows duy trì SSH tunnel:
   `ssh -N -L 127.0.0.1:18018:127.0.0.1:8018 gns3@192.168.211.128`
4. Khởi động Web trên Windows bằng bản mã đang dùng; kiểm tra `http://127.0.0.1:8080` và `http://127.0.0.1:18018/v1/lab/health`.
5. Chỉ chạy smoke test 10 slot khi cần; không chạy lại benchmark 500 slot để kiểm tra giao diện.

Các địa chỉ 192.168.211.128 / port ở trên chỉ đúng với môi trường đã nghiệm thu; cần thay theo VM ở máy khác.
