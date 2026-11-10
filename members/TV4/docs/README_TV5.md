# TV4 - HUONG DAN TICH HOP CORE NETWORK SRv6 VOI TV5

## 1. Mo hinh
- GNS3 VM: Core Network SRv6
- Core Controller: cong 8018 tren GNS3 VM
- Windows SSH Tunnel: http://127.0.0.1:18018
- eMBB: bang 100, mac dinh qua R2
- URLLC: bang 101, mac dinh qua R3

## 2. Ket noi API
Mo PowerShell rieng va chay:

ssh -N -L 18018:127.0.0.1:8018 gns3@GNS3_VM_IP

Thay GNS3_VM_IP bang dia chi IPv4 thuc te cua GNS3 VM.
Giu cua so SSH mo trong qua trinh kiem thu.

Luu y: 127.0.0.1:18018 chi su dung tren may Windows mo SSH Tunnel.

## 3. Danh sach API
GET  /health
GET  /policies
POST /apply-policy
POST /v1/policy/apply
GET  /core-kpi?slice_id=embb
GET  /core-kpi?slice_id=urllc
GET  /v1/events

## 4. Mau yeu cau chuyen Policy
POST /apply-policy
Content-Type: application/json

{
  "request_id": "tv5-demo-001",
  "slice_id": "embb",
  "policy": "low_latency"
}

Khong co confirm: chi preview, khong thay doi mang.

Chi khi duoc phep thay doi mang that moi bo sung:
"confirm": "APPLY_TV4"

Moi yeu cau moi can request_id rieng.
Gui lai cung request_id va cung hanh dong co the tra ket qua da luu.
Dung lai request_id cho hanh dong khac se bi tu choi voi HTTP 409.

## 5. Du lieu Core KPI
GET /core-kpi?slice_id=embb
GET /core-kpi?slice_id=urllc

Cac truong quan trong:
- status
- slice_id
- core_kpi.active_policy
- core_kpi.rtt_ms
- core_kpi.rtt_p95_ms
- core_kpi.throughput_mbps
- core_kpi.jitter_ms
- core_kpi.packet_loss
- core_kpi.switching_time_ms
- measurement.is_live

Luu y:
- KPI hien tai la benchmark lich su, KHONG phai real-time.
- RTT la round-trip, KHONG phai do tre mot chieu.
- packet_loss la ty le fraction, can nhan 100 de doi ra phan tram.
- switching_time_ms hien chua duoc do, gia tri null.

## 6. Ket qua kiem thu da co
- Doc Policy va KPI: PASS
- Chuyen Policy bang API: PASS
- HTTP 400, 409: PASS
- Idempotency: PASS
- Rollback gia lap: PASS

Chua hoan thanh:
- Kiem thu su co duong truyen thuc te
- Tich hop Orchestrator TV5
- Danh gia End-to-End day du

## 7. Luu y tich hop
TV5 can thong nhat them schema JSON, timeout va cach su dung
du lieu KPI lich su truoc khi ghep voi RAN/Orchestrator.