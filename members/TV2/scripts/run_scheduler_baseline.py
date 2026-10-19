from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

TV1_SRC = (
    REPOSITORY_ROOT
    / "members"
    / "TV1"
    / "src"
)

TV2_SRC = (
    REPOSITORY_ROOT
    / "members"
    / "TV2"
    / "src"
)


for source_dir in (TV1_SRC, TV2_SRC):
    source_text = str(source_dir)

    if source_text not in sys.path:
        sys.path.insert(0, source_text)


from ran.simulator import RANSimulator
from schedulers import SCHEDULERS
from schedulers.action_validator import validate_action


def load_yaml(
    path: Path,
) -> dict[str, Any]:
    """Đọc một tệp YAML và trả về dictionary."""

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        data = yaml.safe_load(file)

    if not isinstance(data, dict):
        raise ValueError(
            f"Nội dung YAML phải là dictionary: {path}"
        )

    return data


def parse_arguments() -> argparse.Namespace:
    """Đọc các tham số dòng lệnh."""

    parser = argparse.ArgumentParser(
        description=(
            "Chạy Static hoặc Queue-Based Scheduler "
            "của TV2 với RAN Simulator của TV1."
        )
    )

    parser.add_argument(
        "--scheduler",
        required=True,
        choices=sorted(SCHEDULERS),
        help=(
            "Tên scheduler cần chạy. "
            "Các giá trị hiện có: static, queue_based."
        ),
    )

    parser.add_argument(
        "--scenario-config",
        required=True,
        type=Path,
        help=(
            "Đường dẫn tới tệp cấu hình kịch bản "
            "của TV1."
        ),
    )

    parser.add_argument(
        "--scheduler-config",
        type=Path,
        default=(
            REPOSITORY_ROOT
            / "members"
            / "TV2"
            / "configs"
            / "schedulers.yaml"
        ),
        help=(
            "Đường dẫn tới tệp cấu hình scheduler "
            "của TV2."
        ),
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Seed của lần chạy. Mặc định: 42.",
    )

    parser.add_argument(
        "--slots",
        type=int,
        default=10,
        help=(
            "Số time slot cần chạy. "
            "Mặc định: 10."
        ),
    )

    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Thư mục lưu kết quả mô phỏng.",
    )

    return parser.parse_args()


def validate_arguments(
    arguments: argparse.Namespace,
) -> None:
    """Kiểm tra tính hợp lệ của tham số đầu vào."""

    if arguments.seed < 0:
        raise ValueError(
            "seed phải là số nguyên không âm"
        )

    if arguments.slots <= 0:
        raise ValueError(
            "slots phải lớn hơn 0"
        )

    if not arguments.scenario_config.is_file():
        raise FileNotFoundError(
            "Không tìm thấy tệp cấu hình kịch bản: "
            f"{arguments.scenario_config}"
        )

    if not arguments.scheduler_config.is_file():
        raise FileNotFoundError(
            "Không tìm thấy tệp cấu hình scheduler: "
            f"{arguments.scheduler_config}"
        )


def run_scheduler(
    arguments: argparse.Namespace,
) -> dict[str, Any]:
    """Chạy scheduler với RAN Simulator."""

    validate_arguments(arguments)

    ran_config = load_yaml(
        arguments.scenario_config
    )

    scheduler_config = load_yaml(
        arguments.scheduler_config
    )

    simulation_config = ran_config.get(
        "simulation"
    )

    if not isinstance(
        simulation_config,
        dict,
    ):
        raise ValueError(
            "Cấu hình TV1 phải có mục simulation"
        )

    common_scheduler_config = (
        scheduler_config.get("common")
    )

    if not isinstance(
        common_scheduler_config,
        dict,
    ):
        raise ValueError(
            "Cấu hình TV2 phải có mục common"
        )

    # Chỉ ghi đè cấu hình trong bộ nhớ.
    # Tệp YAML gốc của TV1 không bị chỉnh sửa.
    simulation_config["seed"] = arguments.seed
    simulation_config["slots"] = arguments.slots

    simulator = RANSimulator(
        ran_config
    )

    scheduler = SCHEDULERS[
        arguments.scheduler
    ]

    state = simulator.reset(
        seed=arguments.seed
    )

    processed_slots = 0

    while not simulator.done:
        action = scheduler.select_action(
            state=state,
            config=scheduler_config,
        )

        validate_action(
            action=action,
            state=state,
            total_rb=simulator.total_rb,
            require_all_rb=bool(
                common_scheduler_config.get(
                    "require_all_rb",
                    True,
                )
            ),
        )

        transition = simulator.apply_action(
            action
        )

        processed_slots += 1

        if transition["done"]:
            break

        next_state = transition[
            "next_state"
        ]

        if next_state is None:
            raise RuntimeError(
                "RAN Simulator trả next_state=None "
                "trước khi mô phỏng hoàn thành"
            )

        state = next_state

    if processed_slots != arguments.slots:
        raise RuntimeError(
            "Số slot đã xử lý không đúng: "
            f"expected={arguments.slots}, "
            f"actual={processed_slots}"
        )

    arguments.output.mkdir(
        parents=True,
        exist_ok=True,
    )

    simulator.export_results(
        arguments.output
    )

    run_summary = (
        simulator.build_run_summary()
    )

    run_manifest = (
        simulator.build_run_manifest()
    )

    conservation_ok = (
        run_summary[
            "urllc_packet_counters"
        ][
            "conservation_ok"
        ]
    )

    result = {
        "status": "ok",
        "scheduler": arguments.scheduler,
        "scenario_id": (
            simulator.scenario_id
        ),
        "seed": simulator.seed,
        "processed_slots": (
            processed_slots
        ),
        "run_id": run_manifest["run_id"],
        "conservation_ok": (
            conservation_ok
        ),
        "output": str(
            arguments.output.resolve()
        ),
    }

    return result


def main() -> None:
    """Điểm bắt đầu của chương trình."""

    arguments = parse_arguments()

    result = run_scheduler(
        arguments
    )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()