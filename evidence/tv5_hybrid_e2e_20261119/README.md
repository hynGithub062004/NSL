# Minh chứng Hybrid E2E TV4–TV5 — 19/11/2026

## 1. Mục đích và phạm vi

Bộ dữ liệu này ghi lại việc phối hợp **RAN Simulator (TV1/TV2)**, bộ chọn chính sách **TV5**, và **Core SRv6 triển khai trong GNS3 (TV4)**. Luồng RAN được tính bằng mô phỏng; các datagram theo lịch phát lại được gửi/nhận qua các node GNS3. Đây là **kiểm chứng Hybrid End-to-End**, **không phải** đo E2E trên giao diện vô tuyến 5G thực tế hoặc chứng nhận SLA của mạng sản xuất.

**Phân biệt các bộ thử:** Ma trận hiệu chuẩn gồm 12 lượt (4 phương án × seed 101–103). Seed 42 có bảng so sánh bốn phương án; seed 43 có đối chứng R2/R3 và minh chứng PCAP đổi tuyến. Không lấy các bộ dữ liệu này thay thế lẫn nhau hay gộp thành một phép đo duy nhất.

## 2. Danh mục dữ liệu

| Tệp | Nội dung |
| --- | --- |
| `bang_tong_hop_A_D_3_seed.csv` | KPI hiệu chuẩn 4 phương án A–D, seed 101–103; tổng 12 lượt |
| `KPI_Hybrid_E2E_chuan_A_D_seed42.csv` | KPI seed 42, phân biệt gói URLLC hoàn thành và đúng hạn Hybrid |
| `KPI_Hybrid_E2E_chuan_R2_R3_seed43.csv` | Đối chứng seed 43 cùng lịch RAN: eMBB trên R2 và TV5 chuyển sang R3 |
| `audit_TV5_V2_seed43.json` | Audit chọn chính sách, thực thi, kiểm tra và khôi phục Core của TV5 V2 |
| `R2_baseline.pcap`, `R3_baseline.pcap` | Bắt gói trên hai nhánh ở cấu hình mặc định |
| `R2_tv5_r3.pcap`, `R3_tv5_r3.pcap` | Bắt gói sau khi chuyển eMBB sang R3 |

**Mã nguồn tương ứng:** `members/TV5/e2e/joint_policy_selector.py`, `tv5_joint_runner_d.py`, `tv5_joint_pipeline_v2.py`, `test_joint_policy_selector.py`; lịch phát và đo KPI ở `export_ran_schedule_tv2.py`, `evaluate_e2e.py`; chương trình phát/nhận ở `members/TV4/e2e/`.

## 3. Kết quả tiêu biểu

### Seed 42 — so sánh A–D

| Phương án | eMBB route | Scheduler | URLLC hoàn thành | URLLC đúng hạn Hybrid | Trễ Hybrid (ms) | Goodput eMBB (Mbps) |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| A | R2 | Static | 35/35 | 35/35 | 2.731 | 8.537 |
| B | R2 | QoS Heuristic | 34/35 | 34/35 | 3.034 | 11.365 |
| C | R3 | Static | 35/35 | 35/35 | 2.866 | 9.616 |
| D | R3 | QoS Heuristic | 34/35 | **32/35** | 3.538 | 12.197 |

**Quan trọng:** Giá trị `34/35` của D phản ánh số gói hoàn thành/đến Server, còn **32/35** mới là số gói đúng hạn **Hybrid**. D có goodput cao hơn trong lượt thử nhưng không tốt nhất về URLLC. Các bảng KPI chuẩn hóa giữ tách riêng hai trường này.

### Seed 43 — đối chứng cùng scheduler Static

| KPI | Static + R2 | TV5 V2 chọn R3 |
| --- | ---: | ---: |
| URLLC phát sinh | 39 | 39 |
| URLLC hoàn thành, đến Server | 36 | 36 |
| URLLC đúng hạn Hybrid | **36/39 (92.31%)** | 34/39 (87.18%) |
| Trễ Hybrid trung bình (ms) | **2.979** | 3.442 |
| Goodput eMBB quan sát (Mbps) | 9.977 | **10.566** |
| Datagram gửi/nhận | 114/114 | 114/114 |

Trong lượt seed 43, lựa chọn R3 cho eMBB giúp goodput quan sát tăng khoảng **5.9%**, nhưng tỷ lệ URLLC đúng hạn giảm **5.13 điểm phần trăm** và trễ Hybrid tăng. Đây là **sự đánh đổi**, không chứng minh R3 luôn tốt hơn R2.

## 4. Minh chứng SRv6 bằng PCAP

- **Baseline:** R2 ghi nhận gói eMBB có inner IPv6 nguồn `2001:db8:10::2`, đích `2001:db8:40::2`, UDP đích `5502`, với SRH IPv6 Routing Type 4 và SID R2 (`2001:db8:200::2`) rồi R4 (`2001:db8:400::4`). R3 ghi nhận luồng URLLC UDP `5501` qua SID R3.
- **TV5 chọn R3:** R3 ghi nhận gói eMBB UDP đích `5502` với SID R3 `2001:db8:300::3` rồi R4; R2 không ghi nhận gói trong cửa sổ bắt gói được kiểm tra. File `R2_tv5_r3.pcap` chỉ có header PCAP 24 byte là bình thường.
- Tổng số gói mà `tcpdump` ghi nhận ở hai lượt có thể gồm lưu lượng khác/ICMPv6, **không được** dùng thay cho số datagram ứng dụng, throughput hoặc packet loss. Bằng chứng tại đầu vào R2/R3 kết hợp log gửi/nhận Server hỗ trợ xác nhận đổi nhánh trong phòng thí nghiệm; PCAP riêng lẻ không chứng minh mọi chặng mạng.

## 5. Cách đọc và giới hạn KPI

- `URLLC_HoanThanh`/`URLLC_ServerNhan`: số gói hoàn thành tại RAN/đến Server; **không đồng nghĩa** gói kịp deadline.
- `URLLC_DungHanHybrid`: so thời gian RAN **mô phỏng** cộng thời gian truyền trong GNS3, sử dụng quy ước đồng hồ và phát lại đã kiểm tra; đây **không phải độ trễ đầu cuối vô tuyến thực**.
- `Goodput_eMBB`: số bit hữu ích nhận được chia cho **cửa sổ quan sát phát lại ngắn**; có thể dao động theo điều kiện phát lại, không đại diện dung lượng cực đại hay SLA.
- Bộ chọn chính sách dùng **ước lượng từ hiệu chuẩn độc lập** và quyết định theo ràng buộc. TV5 V2 hiện chỉ kiểm chứng cho `stable_load`, 25 slot, 50 RB, scheduler Static/QoS và lựa chọn tuyến R2/R3; không khẳng định tối ưu toàn cục trên mọi scenario/scheduler.
- Các chỉ số RTT, TCP/UDP của những bộ benchmark Core độc lập ở nơi khác trong repo **không phải** KPI Hybrid E2E cùng một gói tin.
- `audit_TV5_V2_seed43.json` và chính sách readback ghi nhận trạng thái áp dụng/khôi phục Core trong lượt chạy; cần kiểm tra trạng thái trong audit khi đối chiếu với máy GNS3.

## 6. Nguồn gốc và toàn vẹn dữ liệu

Các CSV chuẩn hóa được dựng từ JSON KPI gốc sau khi đối chiếu các lượt hiệu chuẩn và seed 42–43. Các PCAP là bản sao từ lần bắt gói trên GNS3. **Không chỉnh sửa file thí nghiệm gốc.** Bộ đầy đủ (log gửi/nhận, KPI gốc, route readback) được bàn giao riêng trong ZIP nghiệm thu TV4–TV5 ngày 19/11/2026. Khi trích dẫn kết quả, nêu rõ **seed, scheduler, policy, KPI và nguồn đo**.

**Ghi chú công bố:** Trước khi push lên repository công khai, kiểm tra lại metadata của audit và PCAP theo chính sách chia sẻ dữ liệu của nhóm. Các địa chỉ IPv6 `2001:db8::/32` là địa chỉ dành cho tài liệu/thí nghiệm, không phải IP định tuyến công cộng thực tế.
