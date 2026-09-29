# Khu vực upload của nhóm

Thư mục này được chia thành 5 khu vực độc lập:

| Thành viên | Thư mục | Phần việc chính |
| --- | --- | --- |
| TV1 | `TV1/` | RAN Simulator |
| TV2 | `TV2/` | Scheduler |
| TV3 | `TV3/` | RL environment/agent |
| TV4 | `TV4/` | Core Network |
| TV5 | `TV5/` | Integration và tổng hợp kết quả |

## Quy ước chung

1. Chỉ upload hoặc sửa file trong thư mục của mình, trừ khi cả nhóm đã thống nhất.
2. Không commit dữ liệu nhạy cảm, file môi trường cục bộ hoặc file tạm.
3. Nên chia mã nguồn, cấu hình, tài liệu và kiểm thử thành các thư mục con rõ ràng.
4. Ghi cách chạy và các phụ thuộc cần thiết vào `README.md` trong thư mục của mình.
5. Khi thay đổi contract do TV1 cung cấp trong `TV1/contracts/`, cần thông báo cho cả nhóm.
