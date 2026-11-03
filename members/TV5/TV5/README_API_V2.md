# TV5 RAN Orchestrator V2 – huong dan theo tung buoc

## Muc dich
Ban V2 bo sung **dieu phoi theo tung slot thong qua API** va hoat dong song song voi `integration_runner.py` va `api_v1.py`. V2 dung **TV1 RAN Simulator that**, **TV2 Static/Queue-Based that**, **TV3 DQN that khi moi truong du thu vien va checkpoint**. Khong co TV4/SRv6; chua co QoS/fallback; khong bao gio dien so lieu Core gia.

## Cai dat (tai thu muc goc NSL-main)

Mo terminal VS Code PowerShell (co `.venv`), da copy patch vao `NSL-main`:

```powershell
python -m pip install -r members/TV5/requirements-api.txt
python -m pytest members/TV5/tests/test_api_v2.py -q
python -m uvicorn members.TV5.api_v2:app --host 127.0.0.1 --port 8001
```

Mo http://127.0.0.1:8001/docs

1. `GET /health` -> `core_connected: false`.
2. `POST /sessions` -> nhap `{"scheduler":"queue_based","scenario":"urllc_burst","seed":42,"slots":3}`; sao chep `run_id` tu phan hoi.
3. `GET /sessions/{run_id}/state` -> tra State TV1 cho slot 0.
4. `POST /sessions/{run_id}/decision` -> tra Action TV2 (chua thay doi queue).
5. `POST /sessions/{run_id}/step` -> ap Action vao TV1, tra KPI va next_state.
6. Lam lai 3-5 cho du 3 slot, hoac `POST /sessions/{run_id}/run-to-end` de ket thuc.
7. `GET /sessions/{run_id}/metrics` -> xem so slot, rang buoc RB, duong dan CSV.

File duoc ghi rieng theo moi `run_id` tai `members/TV5/results/api_v2/run-.../unified_without_core.csv`.

**Kiem tra DQN that:** tao session `{"scheduler":"dqn","scenario":"poor_channel","seed":42,"slots":10}`. Neu thieu SB3/torch hoac checkpoint, `POST /sessions` bao loi 503; khong ngam chay Static.

## Gioi han ky thuat
- Day la API chay theo simulator, khong phai bo dieu khien RAN that / 1ms real time. `scheduler_latency_ms` la thoi gian wall-clock tai may chay, khong phai delay packet URLLC.
- Client chay 1 luot duy nhat trong 1 worker; session luu RAM, mat khi restart server. Khong dung `--reload`, nhieu `--workers` hoac chia se cong khai tren Internet cho ban v2.
- `POST /decision` lay Action va validate; `POST /step` moi ap Action vao RAN.
- `GET /metrics` tra tom tat **khong phai bao cao hoc thuat cuoi**. Khi chi chay 10 slot/500, khong dung `run_summary.json` lam ket qua benchmark chinh thuc vi TV1 da chuan bi arrival slot ke tiep. Chi full 500 slot moi export `ran/run_summary.json`.
- QoS + fallback `DQN -> QoS -> Static` se ket noi sau khi TV2 ban giao QoS theo Contract 1.0.0. Hien tai V2 bao loi neu DQN gap su co, khong gia fallback.
- `/apply-policy` hien tra `503` chu y de khong hieu nham da thuc hien SRv6; `selected_policy` chi la nhan anh xa slice. Khong swap policy moi 1ms.
- V2 co khoan do latency va log `request_id`, `run_id`, `selected_scheduler`, `core_status` cho tung slot.
- Goi `run-to-end` co the mat thoi gian voi 500 slot DQN; dung de benchmark offline, khong phai real-time.

## Viec can lam tiep sau V2
1. Chot voi TV2 `qos_heuristic.py` va ten `qos_heuristic`, `action_id=2`, validator, config.
2. Them fallback DQN -> QoS -> Static, log ly do va *thuat toan thuc su duoc su dung*.
3. Chot voi TV4 traffic selector theo slice, giao dien policy va cua so do; dung `run_id` de ghep RAN/Core.
4. Chay benchmark 500 slot x 3 scenario x 3 seed, danh gia Static/Queue/QoS/DQN dong nhat.
