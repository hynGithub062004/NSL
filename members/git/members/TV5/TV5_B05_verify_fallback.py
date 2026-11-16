
import csv
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from members.TV5.orchestrator_v2 import (
    Orchestrator,
    QoSHeuristicScheduler,
    StaticScheduler,
)

EVIDENCE = Path("members/TV5/results/saved_tests")
CSV_PATH = EVIDENCE / "csv" / "TV5_B05_04_Fallback_Results.csv"


class FailingDQN:
    def predict(self, state, request_id):
        raise RuntimeError("SIMULATED_DQN_FAILURE")


def check_case(case_id, fail_dqn, fail_qos, fail_static, expected):
    output = EVIDENCE / "fallback_runs" / case_id

    service = Orchestrator(output_root=output)

    session = service.create(
        scheduler="dqn",
        scenario="poor_channel",
        seed=42,
        slots=1,
        allow_fallback=True,
    )

    run_id = session["run_id"]

    # Chỉ giả lập lỗi trong phiên kiểm thử này.
    # Không sửa checkpoint DQN thật.
    if fail_dqn:
        service._sessions[run_id].agent = FailingDQN()

    with ExitStack() as stack:
        if fail_qos:
            stack.enter_context(
                patch.object(
                    QoSHeuristicScheduler,
                    "select_action",
                    side_effect=RuntimeError("SIMULATED_QOS_FAILURE"),
                )
            )

        if fail_static:
            stack.enter_context(
                patch.object(
                    StaticScheduler,
                    "select_action",
                    side_effect=RuntimeError("SIMULATED_STATIC_FAILURE"),
                )
            )

        if expected == "ERROR":
            try:
                service.decision(run_id)
            except RuntimeError as exc:
                assert "All fallback candidates failed" in str(exc)
                metrics = service.metrics(run_id)
                assert metrics["completed_slots"] == 0
                assert metrics["fallback_count"] == 0
                assert service._sessions[run_id].pending_action is None

                return {
                    "TestID": case_id,
                    "ExpectedScheduler": expected,
                    "ActualScheduler": "NONE",
                    "FallbackUsed": "N/A",
                    "FallbackCount": 0,
                    "CompletedSlots": 0,
                    "ActualTestOutcome": "PASSED",
                    "Note": "No invalid Action applied",
                }

            raise AssertionError(
                "All schedulers failed but decision returned an Action"
            )

        decision = service.decision(run_id)
        step = service.step(run_id)
        metrics = service.metrics(run_id)

        actual = decision["selected_scheduler"]
        used = decision["fallback_used"]
        expected_used = expected != "dqn"

        assert actual == expected
        assert used is expected_used
        assert step["action"]["scheduler"] == expected
        assert metrics["completed_slots"] == 1
        assert metrics["fallback_count"] == int(expected_used)
        assert metrics["rb_conservation_ok"] is True

        # Kiểm tra CSV thực tế do Orchestrator xuất.
        result_file = output / run_id / "unified_without_core.csv"
        assert result_file.is_file()

        with result_file.open(
            newline="", encoding="utf-8-sig"
        ) as file:
            rows = list(csv.DictReader(file))

        assert len(rows) == 2
        assert all(
            row["selected_scheduler"] == expected
            for row in rows
        )
        assert all(
            row["fallback_used"].lower()
            == str(expected_used).lower()
            for row in rows
        )

        return {
            "TestID": case_id,
            "ExpectedScheduler": expected,
            "ActualScheduler": actual,
            "FallbackUsed": used,
            "FallbackCount": metrics["fallback_count"],
            "CompletedSlots": metrics["completed_slots"],
            "ActualTestOutcome": "PASSED",
            "Note": decision.get("fallback_reason", ""),
        }


cases = [
    ("F01", False, False, False, "dqn"),
    ("F02", True, False, False, "qos_heuristic"),
    ("F03", True, True, False, "static"),
    ("F04", True, True, True, "ERROR"),
]

results = []

for case_id, dqn_error, qos_error, static_error, expected in cases:
    try:
        row = check_case(
            case_id, dqn_error, qos_error, static_error, expected
        )
    except Exception as exc:
        row = {
            "TestID": case_id,
            "ExpectedScheduler": expected,
            "ActualScheduler": "FAILED",
            "FallbackUsed": "",
            "FallbackCount": "",
            "CompletedSlots": "",
            "ActualTestOutcome": "FAILED",
            "Note": f"{type(exc).__name__}: {exc}",
        }

    results.append(row)
    print(
        f'{case_id}: {row["ActualTestOutcome"]} | '
        f'Expected={expected} | '
        f'Actual={row["ActualScheduler"]}'
    )

CSV_PATH.parent.mkdir(parents=True, exist_ok=True)

with CSV_PATH.open(
    "w", newline="", encoding="utf-8-sig"
) as file:
    writer = csv.DictWriter(file, fieldnames=list(results[0]))
    writer.writeheader()
    writer.writerows(results)

passed = sum(
    row["ActualTestOutcome"] == "PASSED"
    for row in results
)

print(f"\nFallback tests PASSED: {passed}/{len(results)}")
print(f"CSV saved: {CSV_PATH.resolve()}")

if passed != len(results):
    sys.exit(1)

