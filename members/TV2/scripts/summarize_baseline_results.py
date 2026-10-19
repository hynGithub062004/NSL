from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


SCENARIOS = (
    "stable_load",
    "urllc_burst",
    "poor_channel",
)

SCHEDULERS = (
    "static",
    "queue_based",
)

EXPECTED_SEEDS = (
    42,
    43,
    44,
)

EXPECTED_SLOTS = 500

RUN_COLUMNS = (
    "scenario_id",
    "seed",
    "scheduler",
    "run_id",
    "status",
    "processed_slots",
    "arrived_embb_bits",
    "arrived_urllc_bits",
    "offered_embb_mbps",
    "offered_urllc_mbps",
    "served_embb_bits",
    "served_urllc_bits",
    "served_embb_mbps",
    "served_urllc_mbps",
    "urllc_completion_rate",
    "urllc_drop_rate",
    "urllc_resolved_drop_rate",
    "urllc_unresolved_rate",
    "urllc_delay_sample_count",
    "urllc_mean_delay_ms",
    "urllc_p50_delay_ms",
    "urllc_p95_delay_ms",
    "urllc_max_delay_ms",
    "arrived_packets",
    "completed_packets",
    "dropped_packets",
    "late_completed_packets",
    "unresolved_packets",
    "mean_embb_rb",
    "mean_urllc_rb",
    "min_embb_rb",
    "max_embb_rb",
    "min_urllc_rb",
    "max_urllc_rb",
    "conservation_ok",
)

AGGREGATE_METRICS = (
    "served_embb_mbps",
    "served_urllc_mbps",
    "urllc_completion_rate",
    "urllc_drop_rate",
    "urllc_unresolved_rate",
    "urllc_mean_delay_ms",
    "urllc_p95_delay_ms",
    "mean_embb_rb",
    "mean_urllc_rb",
)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Tổng hợp kết quả benchmark Static và Queue-Based "
            "thành bảng CSV chi tiết và bảng CSV thống kê."
        )
    )

    parser.add_argument(
        "--input-root",
        type=Path,
        required=True,
        help="Thư mục chứa ma trận kết quả benchmark.",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Thư mục lưu các tệp CSV tổng hợp.",
    )

    parser.add_argument(
        "--expected-slots",
        type=int,
        default=EXPECTED_SLOTS,
        help="Số slot dự kiến của mỗi lần chạy. Mặc định: 500.",
    )

    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"JSON root phải là object: {path}")

    return data


def load_transitions(path: Path) -> list[dict[str, Any]]:
    transitions: list[dict[str, Any]] = []

    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue

        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Transition JSON không hợp lệ tại {path}, dòng {line_number}"
            ) from exc

        if not isinstance(data, dict):
            raise ValueError(
                "Transition không phải object tại "
                f"{path}, dòng {line_number}"
            )

        transitions.append(data)

    return transitions


def mean(values: list[float]) -> float:
    return round(statistics.fmean(values), 6)


def sample_standard_deviation(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0

    return round(statistics.stdev(values), 6)


def calculate_rb_statistics(
    transitions: list[dict[str, Any]],
    scheduler: str,
    expected_slots: int,
) -> dict[str, float | int]:
    if len(transitions) != expected_slots:
        raise RuntimeError(
            "Số transition không khớp: "
            f"expected={expected_slots}, actual={len(transitions)}"
        )

    embb_allocations: list[int] = []
    urllc_allocations: list[int] = []

    for index, transition in enumerate(transitions, start=1):
        try:
            action = transition["action"]
            allocation = action["rb_allocation"]
            embb_rb = allocation["embb"]
            urllc_rb = allocation["urllc"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError(
                f"Transition thiếu cấu trúc Action tại dòng {index}"
            ) from exc

        if not isinstance(embb_rb, int) or isinstance(embb_rb, bool):
            raise RuntimeError(f"eMBB RB không phải số nguyên tại transition {index}")

        if not isinstance(urllc_rb, int) or isinstance(urllc_rb, bool):
            raise RuntimeError(f"URLLC RB không phải số nguyên tại transition {index}")

        if embb_rb + urllc_rb != 50:
            raise RuntimeError(
                "Tổng RB không bằng 50 tại transition "
                f"{index}: {allocation}"
            )

        if scheduler == "static" and allocation != {"embb": 25, "urllc": 25}:
            raise RuntimeError(
                "Static không phân bổ 25/25 tại "
                f"transition {index}: {allocation}"
            )

        if scheduler == "queue_based" and (embb_rb < 5 or urllc_rb < 5):
            raise RuntimeError(
                "Queue-Based vi phạm RB tối thiểu tại "
                f"transition {index}: {allocation}"
            )

        embb_allocations.append(embb_rb)
        urllc_allocations.append(urllc_rb)

    return {
        "mean_embb_rb": mean([float(value) for value in embb_allocations]),
        "mean_urllc_rb": mean([float(value) for value in urllc_allocations]),
        "min_embb_rb": min(embb_allocations),
        "max_embb_rb": max(embb_allocations),
        "min_urllc_rb": min(urllc_allocations),
        "max_urllc_rb": max(urllc_allocations),
    }


def read_run(
    *,
    input_root: Path,
    scenario: str,
    scheduler: str,
    seed: int,
    expected_slots: int,
) -> dict[str, Any]:
    run_dir = input_root / scenario / scheduler / f"seed_{seed}"
    summary_path = run_dir / "run_summary.json"
    manifest_path = run_dir / "run_manifest.json"
    transitions_path = run_dir / "transitions.jsonl"

    required_files = (summary_path, manifest_path, transitions_path)
    missing_files = [str(path) for path in required_files if not path.is_file()]

    if missing_files:
        raise FileNotFoundError(
            "Thiếu tệp kết quả:\n" + "\n".join(missing_files)
        )

    summary = load_json(summary_path)
    manifest = load_json(manifest_path)
    transitions = load_transitions(transitions_path)

    if summary.get("status") != "complete":
        raise RuntimeError(f"Run chưa hoàn tất: {run_dir}")

    if summary.get("scenario_id") != scenario:
        raise RuntimeError(f"Sai scenario_id: {run_dir}")

    if summary.get("seed") != seed:
        raise RuntimeError(f"Sai seed: {run_dir}")

    if summary.get("processed_slots") != expected_slots:
        raise RuntimeError(f"Sai processed_slots: {run_dir}")

    if manifest.get("scenario_id") != scenario:
        raise RuntimeError(f"Sai scenario_id trong manifest: {run_dir}")

    if manifest.get("seed") != seed:
        raise RuntimeError(f"Sai seed trong manifest: {run_dir}")

    if manifest.get("processed_slots") != expected_slots:
        raise RuntimeError(f"Sai processed_slots trong manifest: {run_dir}")

    algorithms = manifest.get("algorithms")
    if algorithms != [scheduler]:
        raise RuntimeError(
            "Sai algorithms trong manifest: "
            f"expected={[scheduler]}, actual={algorithms}, run_dir={run_dir}"
        )

    packet_counters = summary.get("urllc_packet_counters")
    if not isinstance(packet_counters, dict):
        raise RuntimeError(f"Thiếu urllc_packet_counters: {run_dir}")

    if packet_counters.get("conservation_ok") is not True:
        raise RuntimeError(f"Packet conservation không đạt: {run_dir}")

    traffic = summary.get("traffic_and_service")
    rates = summary.get("urllc_run_rates")
    delays = summary.get("completed_urllc_delay_ms")

    if not isinstance(traffic, dict):
        raise RuntimeError(f"Thiếu traffic_and_service: {run_dir}")

    if not isinstance(rates, dict):
        raise RuntimeError(f"Thiếu urllc_run_rates: {run_dir}")

    if not isinstance(delays, dict):
        raise RuntimeError(f"Thiếu completed_urllc_delay_ms: {run_dir}")

    rb_statistics = calculate_rb_statistics(
        transitions=transitions,
        scheduler=scheduler,
        expected_slots=expected_slots,
    )

    return {
        "scenario_id": scenario,
        "seed": seed,
        "scheduler": scheduler,
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
        "arrived_packets": packet_counters["arrived"],
        "completed_packets": packet_counters["completed"],
        "dropped_packets": packet_counters["dropped"],
        "late_completed_packets": packet_counters["late_completed"],
        "unresolved_packets": packet_counters["unresolved_at_end"],
        **rb_statistics,
        "conservation_ok": packet_counters["conservation_ok"],
    }


def validate_common_inputs(rows: list[dict[str, Any]]) -> None:
    grouped: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)

    for row in rows:
        key = (str(row["scenario_id"]), int(row["seed"]))
        grouped[key][str(row["scheduler"])] = row

    input_fields = (
        "arrived_embb_bits",
        "arrived_urllc_bits",
        "offered_embb_mbps",
        "offered_urllc_mbps",
    )

    for key, scheduler_rows in grouped.items():
        if set(scheduler_rows) != set(SCHEDULERS):
            raise RuntimeError(f"Thiếu scheduler trong cặp so sánh: {key}")

        static_row = scheduler_rows["static"]
        queue_row = scheduler_rows["queue_based"]

        mismatches = {
            field: (static_row[field], queue_row[field])
            for field in input_fields
            if static_row[field] != queue_row[field]
        }

        if mismatches:
            raise RuntimeError(
                f"Traffic đầu vào không giống nhau tại {key}: {mismatches}"
            )


def write_csv(
    path: Path,
    fieldnames: list[str] | tuple[str, ...],
    rows: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_aggregate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        key = (str(row["scenario_id"]), str(row["scheduler"]))
        grouped[key].append(row)

    aggregate_rows: list[dict[str, Any]] = []

    for scenario in SCENARIOS:
        for scheduler in SCHEDULERS:
            group = grouped[(scenario, scheduler)]

            if len(group) != len(EXPECTED_SEEDS):
                raise RuntimeError(
                    "Số seed không đúng cho "
                    f"{scenario}/{scheduler}: {len(group)}"
                )

            group_seeds = sorted(int(row["seed"]) for row in group)
            if group_seeds != list(EXPECTED_SEEDS):
                raise RuntimeError(
                    "Danh sách seed không đúng cho "
                    f"{scenario}/{scheduler}: {group_seeds}"
                )

            aggregate: dict[str, Any] = {
                "scenario_id": scenario,
                "scheduler": scheduler,
                "seed_count": len(group),
            }

            for metric in AGGREGATE_METRICS:
                values = [float(row[metric]) for row in group]
                aggregate[f"{metric}_mean"] = mean(values)
                aggregate[f"{metric}_std"] = sample_standard_deviation(values)
                aggregate[f"{metric}_min"] = round(min(values), 6)
                aggregate[f"{metric}_max"] = round(max(values), 6)

            aggregate_rows.append(aggregate)

    return aggregate_rows


def build_aggregate_columns() -> list[str]:
    columns = [
        "scenario_id",
        "scheduler",
        "seed_count",
    ]

    for metric in AGGREGATE_METRICS:
        columns.extend(
            [
                f"{metric}_mean",
                f"{metric}_std",
                f"{metric}_min",
                f"{metric}_max",
            ]
        )

    return columns


def main() -> None:
    arguments = parse_arguments()

    if arguments.expected_slots <= 0:
        raise ValueError("expected-slots phải lớn hơn 0")

    if not arguments.input_root.is_dir():
        raise FileNotFoundError(
            f"Không tìm thấy thư mục kết quả: {arguments.input_root}"
        )

    rows: list[dict[str, Any]] = []

    for scenario in SCENARIOS:
        for seed in EXPECTED_SEEDS:
            for scheduler in SCHEDULERS:
                row = read_run(
                    input_root=arguments.input_root,
                    scenario=scenario,
                    scheduler=scheduler,
                    seed=seed,
                    expected_slots=arguments.expected_slots,
                )
                rows.append(row)

    expected_run_count = len(SCENARIOS) * len(EXPECTED_SEEDS) * len(SCHEDULERS)

    if len(rows) != expected_run_count:
        raise RuntimeError(
            "Số run không đúng: "
            f"expected={expected_run_count}, actual={len(rows)}"
        )

    combinations = {
        (row["scenario_id"], row["seed"], row["scheduler"])
        for row in rows
    }

    if len(combinations) != expected_run_count:
        raise RuntimeError("Có tổ hợp benchmark bị trùng")

    validate_common_inputs(rows)
    aggregate_rows = build_aggregate_rows(rows)

    runs_path = arguments.output_dir / "baseline_runs.csv"
    aggregate_path = arguments.output_dir / "baseline_aggregate.csv"

    write_csv(path=runs_path, fieldnames=RUN_COLUMNS, rows=rows)
    write_csv(
        path=aggregate_path,
        fieldnames=build_aggregate_columns(),
        rows=aggregate_rows,
    )

    print(f"BASELINE RUNS: {len(rows)} ROWS")
    print(f"BASELINE AGGREGATES: {len(aggregate_rows)} ROWS")
    print(f"Runs CSV: {runs_path.resolve()}")
    print(f"Aggregate CSV: {aggregate_path.resolve()}")
    print("SUMMARY OUTPUT: PASS")


if __name__ == "__main__":
    main()
