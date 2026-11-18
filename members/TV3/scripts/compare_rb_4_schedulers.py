
"""Compare RB usage, backlog and Jain fairness for four schedulers.

Run from NSL root:
  python members/TV3/scripts/compare_rb_4_schedulers.py

DQN v3 results are written to rb_analysis_v3.
Existing v2 results are not overwritten.
"""
from __future__ import annotations

import argparse
import csv
import copy
import hashlib
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

for path in (
    ROOT,
    ROOT / "members" / "TV1" / "src",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import yaml

from members.TV1.src.ran import RANSimulator
from members.TV2.src.schedulers import SCHEDULERS
from members.TV3.dqn_scheduler import DQNScheduler

SCENARIOS = (
    "stable_load",
    "urllc_burst",
    "poor_channel",
)

SEEDS = (42, 43, 44)

SCHEDULERS_TO_COMPARE = (
    "static",
    "queue_based",
    "qos_heuristic",
    "dqn",
)

DEFAULT_OUTPUT = (
    ROOT / "members" / "TV3" /
    "results" / "rb_analysis_v3"
)

DEFAULT_MODEL = (
    ROOT / "members" / "TV3" /
    "models" / "dqn_v3_best.zip"
)

CONFIG = (
    ROOT / "members" / "TV2" /
    "configs" / "schedulers.yaml"
)

METRICS = (
    "embb_mbps",
    "urllc_mbps",
    "urllc_completion_rate",
    "urllc_drop_rate",
    "allocated_embb_rb_mean",
    "allocated_urllc_rb_mean",
    "used_embb_rb_mean",
    "used_urllc_rb_mean",
    "unused_rb_mean",
    "rb_utilization_pct",
    "embb_allocated_rb_utilization_pct",
    "urllc_allocated_rb_utilization_pct",
    "embb_backlog_bits_mean",
    "urllc_backlog_bits_mean",
    "jain_service_satisfaction_mean",
    "jain_rb_allocation_mean",
)


def save_csv(
    path: Path,
    rows: list[dict],
) -> None:
    if not rows:
        raise ValueError(
            f"Cannot write empty CSV: {path}"
        )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
        )
        writer.writeheader()
        writer.writerows(rows)


def mean(values) -> float:
    return statistics.fmean(values)


def jain_rb(
    embb: int,
    urllc: int,
) -> float:
    # Allocation balance, not TV1's service fairness.
    denominator = 2 * (
        embb * embb + urllc * urllc
    )

    return (
        (embb + urllc) ** 2 / denominator
        if denominator
        else 1.0
    )


def execute_run(
    scenario: str,
    seed: int,
    algorithm: str,
    config: dict,
    dqn: DQNScheduler,
) -> tuple[dict, list[dict], tuple]:

    ran = RANSimulator.from_yaml(
        ROOT / "members" / "TV1" /
        "configs" / f"{scenario}.yaml"
    )

    scheduler_cfg = copy.deepcopy(config)

    scheduler_cfg.setdefault(
        "common", {}
    )["slot_duration_ms"] = ran.slot_duration_ms

    if (
        int(scheduler_cfg["common"]["total_rb"])
        != ran.total_rb
    ):
        raise ValueError(
            "TV1/TV2 total_rb mismatch"
        )

    state = ran.reset(seed=seed)
    slot_rows: list[dict] = []

    while not ran.done:
        t = int(state["time_slot"])

        request_id = (
            f"rb-{scenario}-{seed}-{algorithm}-{t}"
        )

        if algorithm == "dqn":
            action = dqn.predict(
                state=state,
                request_id=request_id,
            )
        else:
            action = SCHEDULERS[
                algorithm
            ].select_action(
                state=state,
                config=scheduler_cfg,
                request_id=request_id,
            )

        result = ran.apply_action(action)
        kpi = result["ran_kpi"]

        ae = int(kpi["allocated_embb_rb"])
        au = int(kpi["allocated_urllc_rb"])
        ue = int(kpi["used_embb_rb"])
        uu = int(kpi["used_urllc_rb"])

        if (
            ae + au != ran.total_rb
            or ue > ae
            or uu > au
        ):
            raise AssertionError(
                f"Invalid RB bookkeeping at "
                f"{scenario}, {seed}, {algorithm}, {t}"
            )

        slot_rows.append({
            "scenario_id": scenario,
            "seed": seed,
            "scheduler": algorithm,
            "time_slot": t,

            "embb_backlog_bits_before_service":
                int(state["embb"]["queue_bits"]),

            "urllc_backlog_bits_before_service":
                int(state["urllc"]["queue_bits"]),

            "allocated_embb_rb": ae,
            "allocated_urllc_rb": au,
            "used_embb_rb": ue,
            "used_urllc_rb": uu,

            "unused_rb": ran.total_rb - ue - uu,
            "rb_utilization": float(
                kpi["rb_utilization"]
            ),

            "jain_service_satisfaction": float(
                kpi["fairness"]
            ),

            "jain_rb_allocation": round(
                jain_rb(ae, au), 6
            ),
        })

        state = result["next_state"]

    summary = ran.build_run_summary()

    if (
        summary["status"] != "complete"
        or not summary[
            "urllc_packet_counters"
        ]["conservation_ok"]
    ):
        raise AssertionError(
            f"Incomplete run or conservation error: "
            f"{scenario}/{seed}/{algorithm}"
        )

    n = int(summary["processed_slots"])

    if n != 500 or len(slot_rows) != n:
        raise AssertionError(
            f"Unexpected slots: "
            f"{scenario}/{seed}/{algorithm} ({n})"
        )

    total_alloc_embb = sum(
        r["allocated_embb_rb"]
        for r in slot_rows
    )
    total_alloc_urllc = sum(
        r["allocated_urllc_rb"]
        for r in slot_rows
    )
    total_used_embb = sum(
        r["used_embb_rb"]
        for r in slot_rows
    )
    total_used_urllc = sum(
        r["used_urllc_rb"]
        for r in slot_rows
    )

    traffic = summary["traffic_and_service"]
    rates = summary["urllc_run_rates"]

    run = {
        "scenario_id": scenario,
        "seed": seed,
        "scheduler": algorithm,
        "processed_slots": n,
        "total_rb": ran.total_rb,

        "arrived_embb_bits":
            int(traffic["arrived_embb_bits"]),

        "arrived_urllc_bits":
            int(traffic["arrived_urllc_bits"]),

        "embb_mbps":
            float(traffic["served_embb_mbps"]),

        "urllc_mbps":
            float(traffic["served_urllc_mbps"]),

        "urllc_completion_rate":
            float(rates["completion_rate"]),

        "urllc_drop_rate":
            float(rates["drop_rate_total"]),

        "allocated_embb_rb_mean":
            total_alloc_embb / n,

        "allocated_urllc_rb_mean":
            total_alloc_urllc / n,

        "used_embb_rb_mean":
            total_used_embb / n,

        "used_urllc_rb_mean":
            total_used_urllc / n,

        "unused_rb_mean":
            (
                ran.total_rb * n
                - total_used_embb
                - total_used_urllc
            ) / n,

        "rb_utilization_pct":
            100 * (
                total_used_embb + total_used_urllc
            ) / (ran.total_rb * n),

        "embb_allocated_rb_utilization_pct":
            (
                100 * total_used_embb / total_alloc_embb
                if total_alloc_embb
                else 0.0
            ),

        "urllc_allocated_rb_utilization_pct":
            (
                100 * total_used_urllc / total_alloc_urllc
                if total_alloc_urllc
                else 0.0
            ),

        "embb_backlog_bits_mean":
            mean(
                r["embb_backlog_bits_before_service"]
                for r in slot_rows
            ),

        "urllc_backlog_bits_mean":
            mean(
                r["urllc_backlog_bits_before_service"]
                for r in slot_rows
            ),

        "jain_service_satisfaction_mean":
            mean(
                r["jain_service_satisfaction"]
                for r in slot_rows
            ),

        "jain_rb_allocation_mean":
            mean(
                r["jain_rb_allocation"]
                for r in slot_rows
            ),
    }

    offered = (
        run["arrived_embb_bits"],
        run["arrived_urllc_bits"],
    )

    return run, slot_rows, offered


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--model",
        type=Path,
        default=DEFAULT_MODEL,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )

    args = parser.parse_args()

    if not args.model.is_file():
        parser.error(
            f"Missing DQN v3 checkpoint: {args.model}"
        )

    manifest_file = (
        ROOT / "members" / "TV3" /
        "results" / "training_v3" /
        "training_manifest.json"
    )

    if not manifest_file.is_file():
        parser.error(
            "Missing v3 training_manifest.json; train v3 first"
        )

    with manifest_file.open(
        "r",
        encoding="utf-8",
    ) as f:
        manifest = json.load(f)

    model_hash = hashlib.sha256(
        args.model.read_bytes()
    ).hexdigest()

    if (
        model_hash
        != manifest["best_checkpoint_sha256"]
    ):
        parser.error(
            "Checkpoint does not match "
            "DQN v3 training manifest"
        )

    for name in (
        "rb_efficiency_runs.csv",
        "rb_efficiency_aggregate.csv",
        "rb_slot_metrics.csv",
    ):
        if (args.output / name).exists():
            parser.error(
                f"Output already exists: "
                f"{args.output / name}"
            )

    if not CONFIG.is_file():
        raise FileNotFoundError(
            f"Missing TV2 config: {CONFIG}"
        )

    with CONFIG.open(
        "r",
        encoding="utf-8",
    ) as handle:
        config = yaml.safe_load(handle)

    dqn = DQNScheduler(
        model_path=args.model
    )

    run_rows: list[dict] = []
    all_slots: list[dict] = []

    for scenario in SCENARIOS:
        for seed in SEEDS:
            reference_offered = None

            for algorithm in SCHEDULERS_TO_COMPARE:
                if algorithm not in (
                    "dqn",
                    *SCHEDULERS,
                ):
                    raise ValueError(
                        f"Missing TV2 scheduler: {algorithm}"
                    )

                result, slot_rows, offered = execute_run(
                    scenario,
                    seed,
                    algorithm,
                    config,
                    dqn,
                )

                if reference_offered is None:
                    reference_offered = offered
                elif offered != reference_offered:
                    raise AssertionError(
                        f"Offered traffic NOT matched: "
                        f"{scenario}/{seed}/{algorithm}"
                    )

                run_rows.append(result)
                all_slots.extend(slot_rows)

                print(
                    f"PASS {scenario:14} "
                    f"seed={seed} "
                    f"scheduler={algorithm:14} "
                    f"utilization="
                    f"{result['rb_utilization_pct']:.2f}%"
                )

    aggregated: list[dict] = []

    for scenario in SCENARIOS:
        for algorithm in SCHEDULERS_TO_COMPARE:
            group = [
                r
                for r in run_rows
                if (
                    r["scenario_id"] == scenario
                    and r["scheduler"] == algorithm
                )
            ]

            if len(group) != len(SEEDS):
                raise AssertionError(
                    "Incorrect seed count"
                )

            row = {
                "scenario_id": scenario,
                "scheduler": algorithm,
                "seed_count": len(group),
            }

            for metric in METRICS:
                values = [
                    float(r[metric])
                    for r in group
                ]

                row[
                    f"{metric}_mean"
                ] = round(
                    statistics.fmean(values),
                    6,
                )

                row[
                    f"{metric}_std"
                ] = round(
                    statistics.stdev(values),
                    6,
                )

            aggregated.append(row)

    save_csv(
        args.output / "rb_efficiency_runs.csv",
        run_rows,
    )

    save_csv(
        args.output / "rb_efficiency_aggregate.csv",
        aggregated,
    )

    save_csv(
        args.output / "rb_slot_metrics.csv",
        all_slots,
    )

    print(
        "\nPASS: 36/36 runs, 18,000 slots, "
        "3 seeds, traffic matched, conservation OK"
    )
    print(f"RESULTS: {args.output}")
    print(
        "Jain(service) = TV1 fairness KPI; "
        "Jain(RB) = allocation balance"
    )


if __name__ == "__main__":
    main()
