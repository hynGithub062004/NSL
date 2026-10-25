
import argparse
import csv
import json
import statistics
from pathlib import Path

from stable_baselines3 import DQN
from network_slicing_env import NetworkSlicingEnv


# ============================================================
# 1. CAU HINH CHUNG - DONG BO VOI TV1 VA TV2
# ============================================================

TV3_DIR = Path(__file__).resolve().parent

SCENARIOS = (
    "stable_load",
    "urllc_burst",
    "poor_channel",
)

SEEDS = (42, 43, 44)

SCHEDULER = "dqn"
TOTAL_RB = 50
EXPECTED_SLOTS = 500


# ============================================================
# 2. COT CSV - GIONG BASELINE_RUNS.CSV CUA TV2
# ============================================================

RUN_COLUMNS = """
scenario_id
seed
scheduler
run_id
status
processed_slots
arrived_embb_bits
arrived_urllc_bits
offered_embb_mbps
offered_urllc_mbps
served_embb_bits
served_urllc_bits
served_embb_mbps
served_urllc_mbps
urllc_completion_rate
urllc_drop_rate
urllc_resolved_drop_rate
urllc_unresolved_rate
urllc_delay_sample_count
urllc_mean_delay_ms
urllc_p50_delay_ms
urllc_p95_delay_ms
urllc_max_delay_ms
arrived_packets
completed_packets
dropped_packets
late_completed_packets
unresolved_packets
mean_embb_rb
mean_urllc_rb
min_embb_rb
max_embb_rb
min_urllc_rb
max_urllc_rb
conservation_ok
""".split()


# KPI dung de tinh mean, std, min, max
# Giong baseline_aggregate.csv cua TV2

AGGREGATE_METRICS = """
served_embb_mbps
served_urllc_mbps
urllc_completion_rate
urllc_drop_rate
urllc_unresolved_rate
urllc_mean_delay_ms
urllc_p95_delay_ms
mean_embb_rb
mean_urllc_rb
""".split()

AGGREGATE_COLUMNS = [
    "scenario_id",
    "scheduler",
    "seed_count",
]

for metric in AGGREGATE_METRICS:
    for suffix in ("mean", "std", "min", "max"):
        AGGREGATE_COLUMNS.append(f"{metric}_{suffix}")


# ============================================================
# 3. DOC JSON
# ============================================================

def read_json(path):
    if not path.is_file():
        raise FileNotFoundError(f"Thieu file: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# 4. CHAY DANH GIA DQN CHO MOT SCENARIO VA SEED
# ============================================================

def evaluate_one(model, scenario, seed, raw_root):

    print(f"\nEvaluating: {scenario} | seed={seed}")

    # NetworkSlicingEnv tu tim config trong members/TV1
    config_path = f"members/TV1/configs/{scenario}.yaml"

    env = NetworkSlicingEnv(config_path=config_path)

    try:
        obs, _ = env.reset(seed=seed)

        done = False
        steps = 0

        while not done:

            action, _ = model.predict(
                obs,
                deterministic=True
            )

            obs, reward, terminated, truncated, info = env.step(
                int(action)
            )

            done = bool(terminated or truncated)
            steps += 1

        if steps != EXPECTED_SLOTS:
            raise RuntimeError(
                f"Sai so slot: {steps}, expected={EXPECTED_SLOTS}"
            )

        output_dir = raw_root / scenario / f"seed_{seed}"

        # Xuat du lieu goc truc tiep tu TV1
        env.ran.export_results(output_dir)

        print(f"PASS: {steps} slots")

    finally:
        env.close()


# ============================================================
# 5. DOC LOG TV1 VA TAO MOT DONG DQN_RUNS.CSV
# ============================================================

def build_run_row(raw_root, scenario, seed):

    folder = raw_root / scenario / f"seed_{seed}"

    summary = read_json(folder / "run_summary.json")
    manifest = read_json(folder / "run_manifest.json")

    transitions_file = folder / "transitions.jsonl"

    if not transitions_file.is_file():
        raise FileNotFoundError(transitions_file)

    with transitions_file.open("r", encoding="utf-8") as f:
        transitions = [
            json.loads(line)
            for line in f
            if line.strip()
        ]

    if summary["status"] != "complete":
        raise RuntimeError("Run chua hoan thanh")

    if summary["processed_slots"] != EXPECTED_SLOTS:
        raise RuntimeError("Sai so slot")

    if len(transitions) != EXPECTED_SLOTS:
        raise RuntimeError("So transition khong hop le")

    if (
        summary["scenario_id"] != scenario
        or int(summary["seed"]) != seed
    ):
        raise RuntimeError("Sai scenario hoac seed")

    if manifest.get("algorithms") != [SCHEDULER]:
        raise RuntimeError("Sai scheduler trong manifest")

    packets = summary["urllc_packet_counters"]
    traffic = summary["traffic_and_service"]
    rates = summary["urllc_run_rates"]
    delays = summary["completed_urllc_delay_ms"]

    if packets["conservation_ok"] is not True:
        raise RuntimeError("Packet conservation FAILED")

    # Lay RB allocation tu Action cua TV3
    embb_rb = []
    urllc_rb = []

    for transition in transitions:

        action = transition["action"]

        if action["scheduler"] != SCHEDULER:
            raise RuntimeError("Action khong phai DQN")

        allocation = action["rb_allocation"]

        e = allocation["embb"]
        u = allocation["urllc"]

        if (
            type(e) is not int
            or type(u) is not int
            or e < 0
            or u < 0
            or e + u != TOTAL_RB
        ):
            raise RuntimeError(
                f"RB allocation khong hop le: {allocation}"
            )

        embb_rb.append(e)
        urllc_rb.append(u)

    # Tao row theo dung ten cot cua TV2
    row = {
        "scenario_id": scenario,
        "seed": seed,
        "scheduler": SCHEDULER,
        "run_id": manifest["run_id"],
        "status": summary["status"],
        "processed_slots": summary["processed_slots"],

        "arrived_embb_bits": traffic["arrived_embb_bits"],
        "arrived_urllc_bits": traffic["arrived_urllc_bits"],

        "offered_embb_mbps": traffic["offered_embb_mbps"],
        "offered_urllc_mbps": traffic["offered_urllc_mbps"],

        "served_embb_bits": traffic["served_embb_bits"],
        "served_urllc_bits": traffic["served_urllc_bits"],

        "served_embb_mbps": traffic["served_embb_mbps"],
        "served_urllc_mbps": traffic["served_urllc_mbps"],

        "urllc_completion_rate": rates["completion_rate"],
        "urllc_drop_rate": rates["drop_rate_total"],
        "urllc_resolved_drop_rate": rates["resolved_drop_rate"],
        "urllc_unresolved_rate": rates["unresolved_rate"],

        "urllc_delay_sample_count": delays["sample_count"],
        "urllc_mean_delay_ms": delays["mean"],
        "urllc_p50_delay_ms": delays["p50_nearest_rank"],
        "urllc_p95_delay_ms": delays["p95_nearest_rank"],
        "urllc_max_delay_ms": delays["max"],

        "arrived_packets": packets["arrived"],
        "completed_packets": packets["completed"],
        "dropped_packets": packets["dropped"],
        "late_completed_packets": packets["late_completed"],
        "unresolved_packets": packets["unresolved_at_end"],

        "mean_embb_rb": round(statistics.fmean(embb_rb), 6),
        "mean_urllc_rb": round(statistics.fmean(urllc_rb), 6),

        "min_embb_rb": min(embb_rb),
        "max_embb_rb": max(embb_rb),
        "min_urllc_rb": min(urllc_rb),
        "max_urllc_rb": max(urllc_rb),

        "conservation_ok": packets["conservation_ok"],
    }

    return row


# ============================================================
# 6. KIEM TRA TRAFFIC DQN CO GIONG TV2 KHONG
# ============================================================

def verify_baseline_traffic(rows):

    baseline_path = (
        TV3_DIR.parent
        / "TV2"
        / "results"
        / "baseline_runs.csv"
    )

    if not baseline_path.is_file():
        print("WARNING: Chua co baseline_runs.csv de doi chieu")
        return

    with baseline_path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:

        baseline_rows = list(csv.DictReader(f))

    baseline_map = {
        (r["scenario_id"], int(r["seed"])): r
        for r in baseline_rows
        if r["scheduler"] == "static"
    }

    fields = (
        "arrived_embb_bits",
        "arrived_urllc_bits",
        "offered_embb_mbps",
        "offered_urllc_mbps",
    )

    for row in rows:

        key = (row["scenario_id"], row["seed"])
        baseline = baseline_map.get(key)

        if baseline is None:
            raise RuntimeError(f"Thieu baseline: {key}")

        for field in fields:

            if str(row[field]) != str(baseline[field]):

                raise RuntimeError(
                    f"TRAFFIC MISMATCH: {key}, {field}"
                )

    print("PASS: DQN va TV2 su dung cung offered traffic")


# ============================================================
# 7. TAO DQN_AGGREGATE.CSV
# ============================================================

def build_aggregate(rows):

    aggregate_rows = []

    for scenario in SCENARIOS:

        group = [
            row for row in rows
            if row["scenario_id"] == scenario
        ]

        if len(group) != len(SEEDS):
            raise RuntimeError("Khong du 3 seed")

        aggregate = {
            "scenario_id": scenario,
            "scheduler": SCHEDULER,
            "seed_count": len(group),
        }

        for metric in AGGREGATE_METRICS:

            values = [
                float(row[metric])
                for row in group
            ]

            stats = {
                "mean": statistics.fmean(values),
                "std": statistics.stdev(values),
                "min": min(values),
                "max": max(values),
            }

            for suffix, value in stats.items():
                aggregate[f"{metric}_{suffix}"] = round(
                    value, 6
                )

        aggregate_rows.append(aggregate)

    return aggregate_rows


# ============================================================
# 8. HAM GHI CSV
# ============================================================

def write_csv(path, columns, rows):

    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=columns
        )

        writer.writeheader()
        writer.writerows(rows)


# ============================================================
# 9. CHUONG TRINH CHINH
# ============================================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--model",
        type=Path,
        default=TV3_DIR / "models" / "dqn_v2_best.zip"
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=TV3_DIR / "results"
    )

    args = parser.parse_args()

    if not args.model.is_file():
        parser.error(f"Khong tim thay model: {args.model}")

    output_dir = args.output
    raw_root = output_dir / "benchmark"

    print("=" * 60)
    print("TV3 - DQN BENCHMARK")
    print("=" * 60)

    model = DQN.load(str(args.model))

    # Chay 9 lan evaluation
    for scenario in SCENARIOS:
        for seed in SEEDS:
            evaluate_one(model, scenario, seed, raw_root)

    # Doc log TV1 va tong hop
    rows = [
        build_run_row(raw_root, scenario, seed)
        for scenario in SCENARIOS
        for seed in SEEDS
    ]

    verify_baseline_traffic(rows)

    aggregate_rows = build_aggregate(rows)

    # Xuat CSV cung cau truc TV2
    runs_path = output_dir / "dqn_runs.csv"
    aggregate_path = output_dir / "dqn_aggregate.csv"

    write_csv(
        runs_path,
        RUN_COLUMNS,
        rows
    )

    write_csv(
        aggregate_path,
        AGGREGATE_COLUMNS,
        aggregate_rows
    )

    print("\n" + "=" * 60)
    print("DQN EVALUATION COMPLETED")
    print("=" * 60)

    print(f"Total runs: {len(rows)}")
    print(f"Scenarios: {len(SCENARIOS)}")
    print(f"Seeds: {list(SEEDS)}")

    print(f"\nCreated: {runs_path}")
    print(f"Created: {aggregate_path}")
    print(f"Raw logs: {raw_root}")

    print("\nSUCCESS: CSV format compatible with TV2")


if __name__ == "__main__":
    main()
