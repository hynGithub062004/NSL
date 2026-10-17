# TV2 Contract Notes

## State 1.0.0

- schema_version: luôn bằng 1.0.0
- time_slot: số nguyên không âm
- scenario_id: chuỗi không rỗng
- seed: số nguyên
- embb.queue_bits: số bit eMBB đang chờ
- embb.cqi: CQI eMBB, từ 1 đến 15
- urllc.queue_packets: số packet URLLC
- urllc.queue_bits: số bit URLLC đang chờ
- urllc.cqi: CQI URLLC, từ 1 đến 15
- urllc.oldest_packet_delay_ms: delay của packet lâu nhất
- urllc.deadline_ms: deadline của URLLC

## Action 1.0.0

- schema_version: luôn bằng 1.0.0
- request_id: chuỗi khớp pattern của schema
- time_slot: phải khớp State
- scheduler: static, queue_based hoặc qos_heuristic
- action_id: số nguyên không âm
- rb_allocation.embb: số RB eMBB
- rb_allocation.urllc: số RB URLLC

## Quy tắc TV2

- Không sinh traffic.
- Không cập nhật queue.
- Không tự tính capacity.
- Không tự tính RAN KPI.
- Tổng RB không vượt 50.
- Khi chạy baseline chính thức, dùng đủ 50 RB.
- Queue-Based sử dụng queue_bits của cả hai slice để cùng đơn vị.