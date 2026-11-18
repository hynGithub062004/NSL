# TV2 Scheduler Handoff for TV5

## Pham vi

TV2 cung cap bon scheduler tren tong 50 RB: Static 25/25, Random, Queue-Based va QoS-Weighted. Cac scheduler sinh Action Contract 1.0.0 de TV1 RANSimulator ap dung.

## Cau hinh chung

- TV1 config: `members/TV1/configs/stable_load.yaml`
- TV2 config: `members/TV2/configs/schedulers.yaml`
- Total RB: 50
- Seed benchmark: 42, 43, 44
- Slots benchmark: 500
- Slot duration: 1 ms

## Dinh danh scheduler

| Ten bao cao | Ten CLI | Lop trien khai | action_id | Quy tac |
|---|---|---|---:|---|
| Static 25/25 | `static` | `StaticScheduler` | 0 | 25 RB eMBB, 25 RB URLLC |
| Queue-Based | `queue_based` | `QueueBasedScheduler` | 1 | Chia theo queue, toi thieu 5 RB moi lop |
| QoS-Weighted | `qos_heuristic` | `QoSHeuristicScheduler` | 2 | Phan bo dong theo queue, CQI va do khan cap URLLC |
| Random 50 RB | `random` | `RandomScheduler` | 3 | Chia ngau nhien 0..50, tong luon bang 50, tai lap theo seed va slot |

## Lenh chay TV1-TV2

### Static 25/25

```cmd
python members\\TV2\\scripts\\run_scheduler_baseline.py --scheduler static --scenario-config members\\TV1\\configs\\stable_load.yaml --seed 42 --slots 500 --output <output_dir>
```

### Random

```cmd
python members\\TV2\\scripts\\run_scheduler_baseline.py --scheduler random --scenario-config members\\TV1\\configs\\stable_load.yaml --seed 42 --slots 500 --output <output_dir>
```

### Queue-Based

```cmd
python members\\TV2\\scripts\\run_scheduler_baseline.py --scheduler queue_based --scenario-config members\\TV1\\configs\\stable_load.yaml --seed 42 --slots 500 --output <output_dir>
```

### QoS-Weighted

```cmd
python members\\TV2\\scripts\\run_scheduler_baseline.py --scheduler qos_heuristic --scenario-config members\\TV1\\configs\\stable_load.yaml --seed 42 --slots 500 --output <output_dir>
```

## Ma tran benchmark chinh thuc

```cmd
python members\\TV2\\scripts\\run_baseline_matrix.py --slots 500 --seeds 42 43 44 --schedulers static random queue_based qos_heuristic --output-root members\\TV2\\runs\\four_scheduler_official
```

Ket qua da xac minh: 36/36 run hoan tat, 18000 transition, 36/36 run bao toan goi.

## Tep tong hop

- `members/TV2/results/four_scheduler_runs.csv`: 36 dong chi tiet.
- `members/TV2/results/four_scheduler_aggregate.csv`: 12 dong tong hop.
- Moi dong tong hop su dung ba seed va tinh mean, sample standard deviation, minimum, maximum.

## Anh xa A-D cua TV5

- A va C dung trace Static 25/25.
- B va D dung trace QoS-Weighted (`qos_heuristic`).
- A-B va C-D phai giu nguyen seed, offered load va so slot khi so sanh scheduler.
- Tep RAN replay sinh tu TV1-TV2 khong phai bang chung chuyen phat thuc te trong GNS3.
