from __future__ import annotations

import argparse
import json
import math
import sys
from copy import deepcopy
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
    """Doc mot tep YAML va tra ve dictionary."""

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        data = yaml.safe_load(file)

    if not isinstance(data, dict):
        raise ValueError(
            f"Noi dung YAML phai la dictionary: {path}"
        )

    return data


def parse_arguments() -> argparse.Namespace:
    """Doc cac tham so dong lenh."""

    parser = argparse.ArgumentParser(
        description=(
            "Chay Static, Queue-Based hoac QoS "
            "Heuristic Scheduler cua TV2 voi "
            "RAN Simulator cua TV1."
        )
    )

    parser.add_argument(
        "--scheduler",
        required=True,
        choices=sorted(SCHEDULERS),
        help=(
            "Ten scheduler can chay. "
            "Cac gia tri hien co: static, "
            "queue_based, qos_heuristic."
        ),
    )

    parser.add_argument(
        "--scenario-config",
        required=True,
        type=Path,
        help=(
            "Duong dan toi tep cau hinh kich ban "
            "cua TV1."
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
            "Duong dan toi tep cau hinh scheduler "
            "cua TV2."
        ),
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Seed cua lan chay. Mac dinh: 42.",
    )

    parser.add_argument(
        "--slots",
        type=int,
        default=10,
        help=(
            "So time slot can chay. "
            "Mac dinh: 10."
        ),
    )

    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Thu muc luu ket qua mo phong.",
    )

    return parser.parse_args()


def validate_arguments(
    arguments: argparse.Namespace,
) -> None:
    """Kiem tra tinh hop le cua tham so dau vao."""

    if arguments.seed < 0:
        raise ValueError(
            "seed phai la so nguyen khong am"
        )

    if arguments.slots <= 0:
        raise ValueError(
            "slots phai lon hon 0"
        )

    if not arguments.scenario_config.is_file():
        raise FileNotFoundError(
            "Khong tim thay tep cau hinh kich ban: "
            f"{arguments.scenario_config}"
        )

    if not arguments.scheduler_config.is_file():
        raise FileNotFoundError(
            "Khong tim thay tep cau hinh scheduler: "
            f"{arguments.scheduler_config}"
        )


def run_scheduler(
    arguments: argparse.Namespace,
) -> dict[str, Any]:
    """Chay scheduler voi RAN Simulator."""

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
            "Cau hinh TV1 phai co muc simulation"
        )

    slot_duration_ms = simulation_config.get(
        "slot_duration_ms"
    )

    if (
        isinstance(slot_duration_ms, bool)
        or not isinstance(
            slot_duration_ms,
            (int, float),
        )
    ):
        raise ValueError(
            "simulation.slot_duration_ms phai la "
            "mot so huu han duong"
        )

    slot_duration_ms = float(
        slot_duration_ms
    )

    if (
        not math.isfinite(slot_duration_ms)
        or slot_duration_ms <= 0
    ):
        raise ValueError(
            "simulation.slot_duration_ms phai la "
            "mot so huu han duong"
        )

    effective_scheduler_config = deepcopy(
        scheduler_config
    )

    effective_common_config = (
        effective_scheduler_config.setdefault(
            "common",
            {},
        )
    )

    if not isinstance(
        effective_common_config,
        dict,
    ):
        raise ValueError(
            "Cau hinh TV2 phai co muc common "
            "dang dictionary"
        )

    effective_common_config[
        "slot_duration_ms"
    ] = slot_duration_ms

    common_scheduler_config = (
        effective_scheduler_config.get(
            "common"
        )
    )

    if not isinstance(
        common_scheduler_config,
        dict,
    ):
        raise ValueError(
            "Cau hinh TV2 phai co muc common"
        )

    # Chi ghi de cau hinh RAN trong bo nho.
    # Tep YAML goc cua TV1 khong bi chinh sua.
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
            config=effective_scheduler_config,
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
                "RAN Simulator tra next_state=None "
                "truoc khi mo phong hoan thanh"
            )

        state = next_state

    if processed_slots != arguments.slots:
        raise RuntimeError(
            "So slot da xu ly khong dung: "
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
    """Diem bat dau cua chuong trinh."""

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
