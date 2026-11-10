# Bộ script TV4 – GNS3 / SRv6 (đã làm đến 04/11/2026)

## Phạm vi chính xác

Bộ này **ghi lại và có thể khôi phục cấu hình** mà TV4 đã triển khai thành công trên GNS3: 6 Docker node Ubuntu, IPv6, tuyến IPv6, các SID SRv6 và chuyển tuyến **thủ công** eMBB/URLLC ở R1. Đây là mã tổng hợp từ **các lệnh đã làm trong cuộc trao đổi**, không phải bản sao trích xuất trực tiếp từ GNS3 VM và chưa được chạy kiểm thử trên máy của bạn tại thời điểm tạo ZIP.

**Chưa có**: Flask REST API, Orchestrator, DQN/OFDMA, đo Core KPI tự động, hai slice độc lập *đồng thời*, tự động dự phòng khi lỗi và GNS3 project gốc. Không nên ghi những phần đó là đã hoàn thành.

## Sơ đồ kết nối (tên interface cần đúng)

```
Client eth0 -- eth0 R1 eth1 -- eth0 R2 eth1 -- eth0 R4 eth2 -- eth0 Server
                    |                              |
                   eth2                           eth1
                    |                              |
                   eth0 R3 eth1 -------------------+
```

**IPv6**:

| Node | Interface / IPv6 |
|---|---|
| Client | eth0 `2001:db8:10::2/64` |
| R1 | eth0 `2001:db8:10::1/64`; eth1 `2001:db8:12::1/64`; eth2 `2001:db8:13::1/64` |
| R2 | eth0 `2001:db8:12::2/64`; eth1 `2001:db8:24::2/64` |
| R3 | eth0 `2001:db8:13::3/64`; eth1 `2001:db8:34::3/64` |
| R4 | eth0 `2001:db8:24::4/64`; eth1 `2001:db8:34::4/64`; eth2 `2001:db8:40::1/64` |
| Server | eth0 `2001:db8:40::2/64` |

SID chính: R2 `2001:db8:200::2` End; R3 `2001:db8:300::3` End; R4 `2001:db8:400::4` End.DX6.

## Các file

- `01_client.sh`: IPv6 + default gateway ở Client.
- `02_r1.sh`: IPv6, forwarding, tuyến SID, **chọn eMBB mặc định** trên R1.
- `03_r2.sh`: IPv6, forwarding, seg6local End trên eth0 (eMBB), tuyến tới R4.
- `04_r3.sh`: IPv6, forwarding, seg6local End trên eth0 (URLLC), tuyến tới R4.
- `05_r4.sh`: IPv6, forwarding, cho phép SRv6 vào eth0/eth1, End.DX6 chuyển tới Server.
- `06_server.sh`: IPv6 + default gateway ở Server.
- `07_r1_select_embb.sh`: chọn đường eMBB đi qua R2 trên R1.
- `08_r1_select_urllc.sh`: chọn đường URLLC đi qua R3 trên R1.
- `09_check_r1.sh`: xem trạng thái SR Policy trên R1.
- `10_test_client.sh`: ping và traceroute từ Client tới Server.
- `11_tcpdump_tham_khao.txt`: lệnh bắt gói chụp minh chứng.
- `restore_from_gns3_vm.sh`: chạy script trên **đúng Docker container** thông qua GNS3 VM.

## Quan trọng trước khi chạy

1. **Đảm bảo đã lưu/export project GNS3 và ảnh minh chứng.** Bộ script này không có file topology `.gns3` hay Docker image `gns3-srv6:1.0`; không thay thế cho backup project/image.
2. Script được viết theo interface `eth0`, `eth1`, `eth2` và cấu trúc đã dùng. Nếu giao diện bị đổi, **không chạy** trước khi sửa đúng.
3. Cần quyền root hoặc Docker container có `CAP_NET_ADMIN`; các bước trước đã chạy thành công trong môi trường của bạn.
4. Chạy `02_r1.sh` sẽ **chuyển về eMBB**, vì đó là policy khởi tạo. Muốn URLLC thì chạy `08_r1_select_urllc.sh` sau.
5. Các lệnh `ip -6 addr replace` và `ip -6 route replace` có thể chạy lại trong cùng cấu hình mà không cần xóa mọi tuyến, nhưng script không phải cơ chế rollback/cleanup khi topology đã bị thay đổi.
6. `2001:db8::/32` là địa chỉ ví dụ (documentation) dùng cho mô phỏng, không định tuyến trên Internet công cộng.

## Cách 1 – Lưu lệnh, chạy riêng từng node

Mở GNS3 Console tương ứng và **dán nội dung bên trong từng file `.sh`** vào terminal của node đó. Nên dùng thứ tự: **Server → R4 → R2 → R3 → R1 → Client**. Nội dung là Bash; có thể bỏ dòng `#!/usr/bin/env bash` khi dán. Sau đó chạy `ping -c 5 2001:db8:40::2` trong Client.

Lưu ý: File `.sh` nằm trên Windows của bạn **không tự xuất hiện** trong Docker container. Nếu muốn gõ `bash ten_script.sh` ngay trong node, cần copy file đó vào đúng container trước.

## Cách 2 – Khôi phục nhanh qua SSH đến GNS3 VM (khuyến nghị)

**Trên Windows PowerShell**, tại thư mục chứa ZIP, thay địa chỉ VM bằng IP hiện tại trên màn hình GNS3 VM:

```powershell
scp .\GNS3_SRv6_TV4_scripts_2026-11-04.zip gns3@GNS3_VM_IP:~/
ssh gns3@GNS3_VM_IP
```

**Bên trong shell GNS3 VM**:

```bash
unzip GNS3_SRv6_TV4_scripts_2026-11-04.zip
cd TV4_SRv6_Scripts_2026-11-04
sudo docker ps --format 'table {{.ID}}\t{{.Names}}\t{{.Image}}'
```

Quan sát kỹ kết quả để gán chính xác 6 ID. Sau đó chạy **với ID thật, không chép nguyên chữ CLIENT_ID**:

```bash
bash restore_from_gns3_vm.sh CLIENT_ID R1_ID R2_ID R3_ID R4_ID SERVER_ID embb
```

Script sẽ in mapping và yêu cầu bạn gõ `YES` để xác nhận trước khi thay đổi các container.

Nếu cần URLLC ngay sau khôi phục, dùng `urllc` làm đối số cuối thay vì `embb`.

**Không chắc ID nào là R1?** Dùng lệnh chỉ đọc để đối chiếu với cấu hình hiện tại:

```bash
for id in $(sudo docker ps -q); do
  echo "=== $id ==="
  sudo docker exec "$id" ip -6 route show 2001:db8:40::/64
 done
```

R1 là container có tuyến `encap seg6 mode encap` đến `2001:db8:40::/64`. Nếu cấu hình vừa bị mất sau restart thì lệnh này **không giúp phân biệt được**; hãy xem tên container trong GNS3 hoặc đối chiếu từng liên kết, tuyệt đối không gán ID theo suy đoán.

Nếu `unzip` chưa có, thử `python3 -m zipfile -e GNS3_SRv6_TV4_scripts_2026-11-04.zip .` trên GNS3 VM.

## Chuyển thủ công eMBB / URLLC

Chỉ chạy trên **R1**:

- `bash 07_r1_select_embb.sh` -> eMBB qua R2.
- `bash 08_r1_select_urllc.sh` -> URLLC qua R3.
- `bash 09_check_r1.sh` -> xem policy đang được áp dụng.

Nếu file không ở trong R1, có thể thực thi qua GNS3 VM với ID của R1:

```bash
sudo docker exec -i R1_ID bash -s < 07_r1_select_embb.sh
sudo docker exec -i R1_ID bash -s < 08_r1_select_urllc.sh
sudo docker exec -i R1_ID bash -s < 09_check_r1.sh
```

**Cảnh báo kiến trúc:** Hai lệnh trên cùng thay tuyến `2001:db8:40::/64` ở R1. Đây là **một policy hoạt động tại một thời điểm**, chưa có phân loại hai slice đồng thời, không được mô tả là hoàn thành Network Slicing độc lập.

## Kiểm tra và lưu ảnh

- Ở Client: `ping -c 5 2001:db8:40::2`.
- Ở R1: `ip -6 route show 2001:db8:40::/64`.
- Xem file `11_tcpdump_tham_khao.txt` để bắt SRH trên R1/R2/R3 và ICMPv6 sau End.DX6 trên R4.
- Dấu `* * *` trong traceroute có thể xuất hiện với SRv6; dùng ping và tcpdump để xác nhận.
- Đường trả về từ Server hiện vẫn dùng R4 -> R2 -> R1; đường đi chiều thuận URLLC qua R3 **không có nghĩa hai chiều đều qua R3**.

## Các giới hạn và hướng làm tiếp

- **Chưa có cấu hình tự lưu trong project:** Những `ip` route, địa chỉ, sysctl đặt trong runtime Docker có thể mất khi node bị tạo lại. Hãy giữ ZIP ở Windows và chạy script khôi phục khi cần, hoặc sau này tích hợp vào startup script GNS3.
- Chưa có Flask/REST API; chưa có dữ liệu Core KPI thực đo ngoài kiểm thử ping và tcpdump.
- Chưa kiểm tra two-slice independent simultaneous traffic. Đây là công việc sau khi thống nhất yêu cầu nhóm.

Bản ghi này dùng để lưu và bàn giao **phần thực tế đã xây dựng**, tránh mất công cấu hình lại khi cần demo.
