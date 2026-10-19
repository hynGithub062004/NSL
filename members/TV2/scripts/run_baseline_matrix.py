from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
TV2_DIR = SCRIPT_PATH.parents[1]
MEMBERS_DIR = TV2_DIR.parent
REPOSITORY_ROOT = MEMBERS_DIR.parent

TV1_DIR = MEMBERS_DIR / "TV1"
TV1_CONFIG_DIR = TV1_DIR / "configs"

TV1_SRC = TV1_DIR / "src"
TV2_SRC = TV2_DIR / "src"

for source_dir in (TV1_SRC, TV2_SRC):
    source_text = str(source_dir)

    if source_text not in sys.path:
        sys.path.insert(0, source_text)


from run_scheduler_baseline import run_scheduler


SCENARIOS = (
    "stable_load",
    "urllc_burst",
    "poor_channel",
)

SCHEDULERS = (
    "static",
    "queue_based",
)

DEFAULT_SEEDS = (
    42,
    43,
    44,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Chạy ma trận benchmark Static và Queue-Based Scheduler "
            "trên các kịch bản chính thức của TV1."
        )
    )

    parser.add_argument(
        "--slots",
        type=int,
        default=500,
        help="Số time slot cho mỗi lần chạy. Mặc định: 500.",
    )

    parser.add_argument(
        "--seeds",
        type=int,
        nargs="+",
        default=list(DEFAULT_SEEDS),
        help="Danh sách seed. Mặc định: 42 43 44.",
    )

    parser.add_argument(
        "--output-root",
        type=Path,
        required=True,
        help="Thư mục gốc lưu toàn bộ kết quả benchmark.",
    )

    parser.add_argument(
        "--scheduler-config",
        type=Path,
        default=TV2_DIR / "configs" / "schedulers.yaml",
        help="Tệp cấu hình scheduler của TV2.",
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Cho phép ghi đè thư mục kết quả đã tồn tại.",
    )

    return parser.parse_args()


def validate_arguments(args: argparse.Namespace) -> None:
    if args.slots <= 0:
        raise ValueError("slots phải lớn hơn 0")

    if not args.seeds:
        raise ValueError("Phải cung cấp ít nhất một seed")

    if any(seed < 0 for seed in args.seeds):
        raise ValueError("Seed không được âm")

    if len(set(args.seeds)) != len(args.seeds):
        raise ValueError("Danh sách seed không được chứa giá trị trùng")

    if not args.scheduler_config.is_file():
        raise FileNotFoundError(
            "Không tìm thấy cấu hình scheduler: "
            f"{args.scheduler_config}"
        )

    for scenario in SCENARIOS:
        scenario_path = TV1_CONFIG_DIR / f"{scenario}.yaml"

        if not scenario_path.is_file():
            raise FileNotFoundError(
                f"Không tìm thấy kịch bản TV1: {scenario_path}"
            )


def build_run_arguments(
    *,
    scheduler: str,
    scenario: str,
    seed: int,
    slots: int,
    scheduler_config: Path,
    output_root: Path,
) -> argparse.Namespace:
    return argparse.Namespace(
        scheduler=scheduler,
        scenario_config=TV1_CONFIG_DIR / f"{scenario}.yaml",
        scheduler_config=scheduler_config,
        seed=seed,
        slots=slots,
        output=(
            output_root
            / scenario
            / scheduler
            / f"seed_{seed}"
        ),
    )


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"JSON root phải là object: {path}")

    return data


def validate_exported_run(
    *,
    output_dir: Path,
    expected_scenario: str,
    expected_scheduler: str,
    expected_seed: int,
    expected_slots: int,
) -> dict[str, Any]:
    summary_path = output_dir / "run_summary.json"
    manifest_path = output_dir / "run_manifest.json"
    transitions_path = output_dir / "transitions.jsonl"

    required_files = (
        output_dir / "traffic_log.csv",
        output_dir / "cqi_log.csv",
        output_dir / "ran_metrics.csv",
        output_dir / "state_log.jsonl",
        transitions_path,
        output_dir / "state_sample.json",
        output_dir / "transition_sample.json",
        summary_path,
        manifest_path,
    )

    missing_files = [
        str(path)
        for path in required_files
        if not path.is_file()
    ]

    if missing_files:
        raise RuntimeError(
            "Thiếu tệp đầu ra:\n"
            + "\n".join(missing_files)
        )

    summary = load_json(summary_path)
    manifest = load_json(manifest_path)

    if summary.get("status") != "complete":
        raise RuntimeError(
            f"Run chưa hoàn tất: {output_dir}"
        )

    if summary.get("scenario_id") != expected_scenario:
        raise RuntimeError(
            "Sai scenario_id trong run_summary.json"
        )

    if summary.get("seed") != expected_seed:
        raise RuntimeError(
            "Sai seed trong run_summary.json"
        )

    if summary.get("processed_slots") != expected_slots:
        raise RuntimeError(
            "Sai processed_slots trong run_summary.json"
        )

    packet_counters = summary.get(
        "urllc_packet_counters",
        {},
    )

    if packet_counters.get("conservation_ok") is not True:
        raise RuntimeError(
            f"Packet conservation không đạt: {output_dir}"
        )

    if manifest.get("scenario_id") != expected_scenario:
        raise RuntimeError(
            "Sai scenario_id trong run_manifest.json"
        )

    if manifest.get("seed") != expected_seed:
        raise RuntimeError(
            "Sai seed trong run_manifest.json"
        )

    if manifest.get("processed_slots") != expected_slots:
        raise RuntimeError(
            "Sai processed_slots trong run_manifest.json"
        )

    algorithms = manifest.get("algorithms")

    if algorithms != [expected_scheduler]:
        raise RuntimeError(
            "Danh sách algorithms không đúng: "
            f"expected={[expected_scheduler]}, "
            f"actual={algorithms}"
        )

    transition_lines = [
        line
        for line in transitions_path.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]

    if len(transition_lines) != expected_slots:
        raise RuntimeError(
            "Số transition không khớp: "
            f"expected={expected_slots}, "
            f"actual={len(transition_lines)}"
        )

    for line_number, line in enumerate(
        transition_lines,
        start=1,
    ):
        transition = json.loads(line)
        action = transition["action"]
        allocation = action["rb_allocation"]

        embb_rb = allocation["embb"]
        urllc_rb = allocation["urllc"]

        if embb_rb + urllc_rb != 50:
            raise RuntimeError(
                "Tổng RB không bằng 50 tại transition "
                f"{line_number}: {allocation}"
            )

        if expected_scheduler == "static":
            if allocation != {
                "embb": 25,
                "urllc": 25,
            }:
                raise RuntimeError(
                    "Static allocation không phải 25/25 "
                    f"tại transition {line_number}: "
                    f"{allocation}"
                )

        if expected_scheduler == "queue_based":
            if embb_rb < 5 or urllc_rb < 5:
                raise RuntimeError(
                    "Queue-Based vi phạm RB tối thiểu "
                    f"tại transition {line_number}: "
                    f"{allocation}"
                )

    return {
        "scenario_id": expected_scenario,
        "scheduler": expected_scheduler,
        "seed": expected_seed,
        "processed_slots": expected_slots,
        "run_id": manifest["run_id"],
        "conservation_ok": True,
        "output_dir": str(output_dir.resolve()),
    }


def validate_common_input(
    static_output: Path,
    queue_output: Path,
) -> None:
    static_summary = load_json(
        static_output / "run_summary.json"
    )

    queue_summary = load_json(
        queue_output / "run_summary.json"
    )

    static_traffic = static_summary[
        "traffic_and_service"
    ]

    queue_traffic = queue_summary[
        "traffic_and_service"
    ]

    keys = (
        "arrived_embb_bits",
        "arrived_urllc_bits",
        "offered_embb_mbps",
        "offered_urllc_mbps",
    )

    mismatches = {
        key: (
            static_traffic[key],
            queue_traffic[key],
        )
        for key in keys
        if static_traffic[key] != queue_traffic[key]
    }

    if mismatches:
        raise RuntimeError(
            "Static và Queue-Based không dùng cùng "
            f"traffic đầu vào: {mismatches}"
        )


def main() -> None:
    args = parse_args()
    validate_arguments(args)

    total_runs = (
        len(SCENARIOS)
        * len(args.seeds)
        * len(SCHEDULERS)
    )

    args.output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    matrix_results: list[dict[str, Any]] = []
    current_run = 0

    for scenario in SCENARIOS:
        for seed in args.seeds:
            outputs: dict[str, Path] = {}

            for scheduler in SCHEDULERS:
                current_run += 1

                run_args = build_run_arguments(
                    scheduler=scheduler,
                    scenario=scenario,
                    seed=seed,
                    slots=args.slots,
                    scheduler_config=args.scheduler_config,
                    output_root=args.output_root,
                )

                output_dir = run_args.output
                outputs[scheduler] = output_dir

                if output_dir.exists() and not args.overwrite:
                    raise FileExistsError(
                        "Thư mục kết quả đã tồn tại: "
                        f"{output_dir}. "
                        "Dùng --overwrite nếu muốn chạy lại."
                    )

                print(
                    f"[{current_run:02}/{total_runs}] "
                    f"{scenario}/{scheduler}/"
                    f"seed_{seed}: RUNNING"
                )

                runner_result = run_scheduler(run_args)

                validated_result = validate_exported_run(
                    output_dir=output_dir,
                    expected_scenario=scenario,
                    expected_scheduler=scheduler,
                    expected_seed=seed,
                    expected_slots=args.slots,
                )

                validated_result["runner_status"] = (
                    runner_result["status"]
                )

                matrix_results.append(
                    validated_result
                )

                print(
                    f"[{current_run:02}/{total_runs}] "
                    f"{scenario}/{scheduler}/"
                    f"seed_{seed}: PASS"
                )

            validate_common_input(
                outputs["static"],
                outputs["queue_based"],
            )

            print(
                f"[INPUT CHECK] {scenario}/seed_{seed}: "
                "PASS"
            )

    matrix_manifest = {
        "status": "complete",
        "slots_per_run": args.slots,
        "scenarios": list(SCENARIOS),
        "seeds": list(args.seeds),
        "schedulers": list(SCHEDULERS),
        "expected_runs": total_runs,
        "completed_runs": len(matrix_results),
        "runs": matrix_results,
    }

    manifest_path = (
        args.output_root
        / "baseline_matrix_manifest.json"
    )

    manifest_path.write_text(
        json.dumps(
            matrix_manifest,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print(
        f"BASELINE MATRIX: "
        f"{len(matrix_results)}/{total_runs} RUNS PASS"
    )

    print(
        f"Manifest: {manifest_path.resolve()}"
    )


if __name__ == "__main__":
    main()
