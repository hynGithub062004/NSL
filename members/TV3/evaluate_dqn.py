
"""Evaluate DQN v3 on three scenarios and three held-out seeds."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from pathlib import Path

from stable_baselines3 import DQN
from network_slicing_env import NetworkSlicingEnv

TV3_DIR = Path(__file__).resolve().parent
ROOT = TV3_DIR.parents[1]

SCENARIOS = (
    "stable_load",
    "urllc_burst",
    "poor_channel",
)
SEEDS = (42, 43, 44)
EXPECTED_SLOTS = 500
TOTAL_RB = 50
SCHEDULER = "dqn"

RUN_COLUMNS = """scenario_id seed scheduler run_id status processed_slots
arrived_embb_bits arrived_urllc_bits offered_embb_mbps offered_urllc_mbps
served_embb_bits served_urllc_bits served_embb_mbps served_urllc_mbps
urllc_completion_rate urllc_drop_rate urllc_resolved_drop_rate
urllc_unresolved_rate urllc_delay_sample_count urllc_mean_delay_ms
urllc_p50_delay_ms urllc_p95_delay_ms urllc_max_delay_ms
arrived_packets completed_packets dropped_packets late_completed_packets
unresolved_packets mean_embb_rb mean_urllc_rb min_embb_rb max_embb_rb
min_urllc_rb max_urllc_rb conservation_ok""".split()

AGGREGATE_METRICS = """served_embb_mbps served_urllc_mbps
urllc_completion_rate urllc_drop_rate urllc_unresolved_rate
urllc_mean_delay_ms urllc_p95_delay_ms mean_embb_rb mean_urllc_rb""".split()

AGGREGATE_COLUMNS = [
    "scenario_id",
    "scheduler",
    "seed_count",
] + [
    f"{metric}_{suffix}"
    for metric in AGGREGATE_METRICS
    for suffix in ("mean", "std", "min", "max")
]


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def digest(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as f:
        for chunk in iter(
            lambda: f.read(1024 * 1024),
            b"",
        ):
            h.update(chunk)

    return h.hexdigest()


def write_csv(
    path: Path,
    columns: list[str],
    rows: list[dict],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=columns,
            extrasaction="raise",
        )
        writer.writeheader()
        writer.writerows(rows)


def evaluate_one(
    model: DQN,
    scenario: str,
    seed: int,
    raw_root: Path,
) -> None:
    env = NetworkSlicingEnv(
        f"members/TV1/configs/{scenario}.yaml"
    )

    try:
        obs, info = env.reset(seed=seed)

        if info["effective_seed"] != seed:
            raise RuntimeError("Benchmark seed mismatch")

        steps = 0
        terminated = False
        truncated = False

        while not (terminated or truncated):
            action, _ = model.predict(
                obs,
                deterministic=True,
            )

            obs, _, terminated, truncated, _ = env.step(
                int(action)
            )
            steps += 1

        if steps != EXPECTED_SLOTS:
            raise RuntimeError(
                f"Wrong slot count: {scenario}/{seed}: {steps}"
            )

        env.ran.export_results(
            raw_root / scenario / f"seed_{seed}"
        )

        print(
            f"PASS: {scenario} seed={seed}, slots={steps}"
        )

    finally:
        env.close()


def build_run_row(
    raw_root: Path,
    scenario: str,
    seed: int,
) -> dict:
    folder = raw_root / scenario / f"seed_{seed}"

    summary = read_json(
        folder / "run_summary.json"
    )
    manifest = read_json(
        folder / "run_manifest.json"
    )

    with (
        folder / "transitions.jsonl"
    ).open("r", encoding="utf-8") as f:
        transitions = [
            json.loads(line)
            for line in f
            if line.strip()
        ]

    if (
        summary["status"] != "complete"
        or summary["processed_slots"] != EXPECTED_SLOTS
        or len(transitions) != EXPECTED_SLOTS
    ):
        raise RuntimeError(
            f"Incomplete run: {scenario}/{seed}"
        )

    if (
        summary["scenario_id"] != scenario
        or int(summary["seed"]) != seed
    ):
        raise RuntimeError(
            "Scenario/seed mismatch"
        )

    if manifest.get("algorithms") != [SCHEDULER]:
        raise RuntimeError(
            "Not a DQN-only run"
        )

    packets = summary["urllc_packet_counters"]

    if packets["conservation_ok"] is not True:
        raise RuntimeError(
            "Packet conservation failed"
        )

    e_rb = []
    u_rb = []

    for i, transition in enumerate(transitions):
        act = transition["action"]

        if (
            act["scheduler"] != SCHEDULER
            or act["time_slot"] != i
        ):
            raise RuntimeError(
                "Scheduler or time slot mismatch"
            )

        e = act["rb_allocation"]["embb"]
        u = act["rb_allocation"]["urllc"]

        if (
            type(e) is not int
            or type(u) is not int
            or e < 0
            or u < 0
            or e + u != TOTAL_RB
        ):
            raise RuntimeError(
                "Invalid RB allocation"
            )

        e_rb.append(e)
        u_rb.append(u)

    traffic = summary["traffic_and_service"]
    rates = summary["urllc_run_rates"]
    delays = summary["completed_urllc_delay_ms"]

    return {
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

        "mean_embb_rb": round(
            statistics.fmean(e_rb), 6
        ),
        "mean_urllc_rb": round(
            statistics.fmean(u_rb), 6
        ),

        "min_embb_rb": min(e_rb),
        "max_embb_rb": max(e_rb),
        "min_urllc_rb": min(u_rb),
        "max_urllc_rb": max(u_rb),

        "conservation_ok": packets["conservation_ok"],
    }


def verify_baseline_traffic(
    rows: list[dict],
) -> None:
    baseline_path = (
        ROOT / "members" / "TV2" /
        "results" / "baseline_runs.csv"
    )

    if not baseline_path.is_file():
        print(
            "WARNING: TV2 baseline_runs.csv missing; "
            "cannot verify offered traffic"
        )
        return

    with baseline_path.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as f:
        reference = {
            (
                r["scenario_id"],
                int(r["seed"]),
            ): r
            for r in csv.DictReader(f)
            if r["scheduler"] == "static"
        }

    for row in rows:
        key = (
            row["scenario_id"],
            int(row["seed"]),
        )

        if key not in reference:
            raise RuntimeError(
                f"Missing TV2 static baseline: {key}"
            )

        base = reference[key]

        for metric in (
            "arrived_embb_bits",
            "arrived_urllc_bits",
        ):
            if int(row[metric]) != int(base[metric]):
                raise RuntimeError(
                    f"Traffic mismatch: {key}, {metric}"
                )

        for metric in (
            "offered_embb_mbps",
            "offered_urllc_mbps",
        ):
            if not math.isclose(
                float(row[metric]),
                float(base[metric]),
                rel_tol=1e-9,
                abs_tol=1e-8,
            ):
                raise RuntimeError(
                    f"Offered rate mismatch: {key}, {metric}"
                )

    print(
        "PASS: DQN v3 traffic matches TV2 static baseline"
    )


def build_aggregate(
    rows: list[dict],
) -> list[dict]:
    result = []

    for scenario in SCENARIOS:
        group = [
            r for r in rows
            if r["scenario_id"] == scenario
        ]

        if (
            len(group) != len(SEEDS)
            or {r["seed"] for r in group} != set(SEEDS)
        ):
            raise RuntimeError(
                f"Missing seed in scenario {scenario}"
            )

        row = {
            "scenario_id": scenario,
            "scheduler": SCHEDULER,
            "seed_count": len(group),
        }

        for metric in AGGREGATE_METRICS:
            values = [
                float(r[metric])
                for r in group
            ]

            for suffix, value in (
                ("mean", statistics.fmean(values)),
                ("std", statistics.stdev(values)),
                ("min", min(values)),
                ("max", max(values)),
            ):
                row[f"{metric}_{suffix}"] = round(
                    value, 6
                )

        result.append(row)

    return result


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--model",
        type=Path,
        default=TV3_DIR / "models" / "dqn_v3_best.zip",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=TV3_DIR / "results" / "benchmark_v3",
    )

    args = parser.parse_args()

    if not args.model.is_file():
        parser.error(
            f"Checkpoint not found: {args.model}"
        )

    train_manifest_path = (
        TV3_DIR / "results" /
        "training_v3" / "training_manifest.json"
    )

    if not train_manifest_path.is_file():
        parser.error(
            "Missing training_v3/training_manifest.json; "
            "train v3 first"
        )

    train_manifest = read_json(
        train_manifest_path
    )

    model_hash = digest(args.model)

    if (
        model_hash
        != train_manifest["best_checkpoint_sha256"]
    ):
        parser.error(
            "Checkpoint SHA-256 does not match "
            "the trained v3 best model"
        )

    if set(
        train_manifest["train_seeds_completed"]
    ) & set(SEEDS):
        parser.error(
            "Benchmark seed overlaps actual training seeds"
        )

    if set(
        train_manifest["validation_seeds"]
    ) & set(SEEDS):
        parser.error(
            "Benchmark seed overlaps validation seeds"
        )

    if (
        args.output.resolve()
        == (TV3_DIR / "results").resolve()
    ):
        parser.error(
            "Refusing to overwrite original "
            "DQN v2 results directory"
        )

    for filename in (
        "dqn_runs.csv",
        "dqn_aggregate.csv",
        "benchmark_manifest.json",
    ):
        if (args.output / filename).exists():
            parser.error(
                f"Output already exists: "
                f"{args.output / filename}"
            )

    model = DQN.load(
        str(args.model),
        device="cpu",
    )

    raw_root = args.output / "raw"

    for scenario in SCENARIOS:
        for seed in SEEDS:
            evaluate_one(
                model,
                scenario,
                seed,
                raw_root,
            )

    rows = [
        build_run_row(
            raw_root,
            s,
            seed,
        )
        for s in SCENARIOS
        for seed in SEEDS
    ]

    verify_baseline_traffic(rows)

    aggregates = build_aggregate(rows)

    write_csv(
        args.output / "dqn_runs.csv",
        RUN_COLUMNS,
        rows,
    )

    write_csv(
        args.output / "dqn_aggregate.csv",
        AGGREGATE_COLUMNS,
        aggregates,
    )

    (
        args.output / "benchmark_manifest.json"
    ).write_text(
        json.dumps(
            {
                "model": "DQN v3",
                "model_sha256": model_hash,
                "checkpoint": str(args.model.resolve()),
                "training_manifest": str(
                    train_manifest_path.resolve()
                ),
                "scenarios": list(SCENARIOS),
                "benchmark_seeds": list(SEEDS),
                "slots_per_run": EXPECTED_SLOTS,
                "runs": len(rows),
                "source": "TV1 RANSimulator",
                "scheduler": SCHEDULER,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(
        "\nPASS: DQN v3 benchmark, 9/9 runs; "
        "DQN v2 files untouched"
    )
    print(f"Results: {args.output}")


if __name__ == "__main__":
    main()
