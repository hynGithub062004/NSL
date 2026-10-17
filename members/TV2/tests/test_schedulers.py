import sys
import unittest
from copy import deepcopy
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


from schedulers import (
    QueueBasedScheduler,
    StaticScheduler,
)
from schedulers.action_validator import (
    ActionValidationError,
    validate_action,
)


BASE_STATE = {
    "schema_version": "1.0.0",
    "time_slot": 0,
    "scenario_id": "stable_load",
    "seed": 42,
    "embb": {
        "queue_bits": 500_000,
        "cqi": 10,
    },
    "urllc": {
        "queue_packets": 250,
        "queue_bits": 640_000,
        "cqi": 8,
        "oldest_packet_delay_ms": 2.0,
        "deadline_ms": 5.0,
    },
}


SCHEDULER_CONFIG = {
    "common": {
        "total_rb": 50,
        "require_all_rb": True,
    },
    "static": {
        "rb_embb": 25,
        "rb_urllc": 25,
        "action_id": 0,
    },
}


QUEUE_BASED_CONFIG = {
    "common": {
        "total_rb": 50,
        "require_all_rb": True,
    },
    "queue_based": {
        "min_rb_embb": 5,
        "min_rb_urllc": 5,
        "action_id": 1,
    },
}


def make_queue_state(
    embb_queue_bits: int,
    urllc_queue_bits: int,
    time_slot: int = 0,
) -> dict:
    """Tạo State hợp lệ để kiểm thử Queue-Based Scheduler."""

    state = deepcopy(BASE_STATE)
    state["time_slot"] = time_slot
    state["embb"]["queue_bits"] = embb_queue_bits
    state["urllc"]["queue_bits"] = urllc_queue_bits
    return state


class StaticSchedulerTests(unittest.TestCase):

    def test_static_allocation(self):
        scheduler = StaticScheduler()
        action = scheduler.select_action(
            BASE_STATE,
            SCHEDULER_CONFIG,
        )
        self.assertEqual(
            action["rb_allocation"],
            {"embb": 25, "urllc": 25},
        )

    def test_action_shape(self):
        action = StaticScheduler().select_action(
            BASE_STATE,
            SCHEDULER_CONFIG,
        )
        self.assertEqual(
            set(action),
            {
                "schema_version",
                "request_id",
                "time_slot",
                "scheduler",
                "action_id",
                "rb_allocation",
            },
        )

    def test_request_id_is_deterministic(self):
        scheduler = StaticScheduler()
        action_1 = scheduler.select_action(
            BASE_STATE,
            SCHEDULER_CONFIG,
        )
        action_2 = scheduler.select_action(
            BASE_STATE,
            SCHEDULER_CONFIG,
        )
        self.assertEqual(
            action_1["request_id"],
            action_2["request_id"],
        )
        self.assertEqual(
            action_1["request_id"],
            "stable_load-42-0",
        )

    def test_explicit_request_id(self):
        action = StaticScheduler().select_action(
            BASE_STATE,
            SCHEDULER_CONFIG,
            request_id="tv5-request-001",
        )
        self.assertEqual(
            action["request_id"],
            "tv5-request-001",
        )

    def test_valid_action(self):
        action = StaticScheduler().select_action(
            BASE_STATE,
            SCHEDULER_CONFIG,
        )
        result = validate_action(
            action=action,
            state=BASE_STATE,
            total_rb=50,
            require_all_rb=True,
        )
        self.assertEqual(result, action)

    def test_invalid_total_rb(self):
        action = StaticScheduler().select_action(
            BASE_STATE,
            SCHEDULER_CONFIG,
        )
        invalid_action = deepcopy(action)
        invalid_action["rb_allocation"]["embb"] = 26
        with self.assertRaises(ActionValidationError):
            validate_action(
                invalid_action,
                BASE_STATE,
                total_rb=50,
                require_all_rb=True,
            )

    def test_wrong_time_slot(self):
        action = StaticScheduler().select_action(
            BASE_STATE,
            SCHEDULER_CONFIG,
        )
        invalid_action = deepcopy(action)
        invalid_action["time_slot"] = 1
        with self.assertRaises(ActionValidationError):
            validate_action(
                invalid_action,
                BASE_STATE,
                total_rb=50,
            )

    def test_invalid_request_id(self):
        action = StaticScheduler().select_action(
            BASE_STATE,
            SCHEDULER_CONFIG,
        )
        invalid_action = deepcopy(action)
        invalid_action["request_id"] = "invalid request id"
        with self.assertRaises(ActionValidationError):
            validate_action(
                invalid_action,
                BASE_STATE,
                total_rb=50,
            )


class QueueBasedSchedulerTests(unittest.TestCase):

    def setUp(self):
        self.scheduler = QueueBasedScheduler()

    def test_equal_queues_use_equal_allocation(self):
        state = make_queue_state(1000, 1000)
        action = self.scheduler.select_action(
            state,
            QUEUE_BASED_CONFIG,
        )
        self.assertEqual(
            action["rb_allocation"],
            {"embb": 25, "urllc": 25},
        )

    def test_larger_embb_queue_receives_more_rb(self):
        state = make_queue_state(3000, 1000)
        action = self.scheduler.select_action(
            state,
            QUEUE_BASED_CONFIG,
        )
        self.assertEqual(
            action["rb_allocation"],
            {"embb": 35, "urllc": 15},
        )

    def test_larger_urllc_queue_receives_more_rb(self):
        state = make_queue_state(1000, 3000)
        action = self.scheduler.select_action(
            state,
            QUEUE_BASED_CONFIG,
        )
        self.assertEqual(
            action["rb_allocation"],
            {"embb": 15, "urllc": 35},
        )

    def test_only_urllc_has_data(self):
        state = make_queue_state(0, 5000)
        action = self.scheduler.select_action(
            state,
            QUEUE_BASED_CONFIG,
        )
        self.assertEqual(
            action["rb_allocation"],
            {"embb": 5, "urllc": 45},
        )

    def test_only_embb_has_data(self):
        state = make_queue_state(5000, 0)
        action = self.scheduler.select_action(
            state,
            QUEUE_BASED_CONFIG,
        )
        self.assertEqual(
            action["rb_allocation"],
            {"embb": 45, "urllc": 5},
        )

    def test_zero_queues_use_equal_allocation(self):
        state = make_queue_state(0, 0)
        action = self.scheduler.select_action(
            state,
            QUEUE_BASED_CONFIG,
        )
        self.assertEqual(
            action["rb_allocation"],
            {"embb": 25, "urllc": 25},
        )

    def test_total_and_minimum_rb_are_preserved(self):
        queue_cases = [
            (0, 0),
            (1000, 1000),
            (3000, 1000),
            (1000, 3000),
            (0, 5000),
            (5000, 0),
            (1234, 5678),
        ]

        for embb_queue, urllc_queue in queue_cases:
            with self.subTest(
                embb_queue=embb_queue,
                urllc_queue=urllc_queue,
            ):
                state = make_queue_state(
                    embb_queue,
                    urllc_queue,
                )
                action = self.scheduler.select_action(
                    state,
                    QUEUE_BASED_CONFIG,
                )
                allocation = action["rb_allocation"]
                self.assertGreaterEqual(
                    allocation["embb"],
                    5,
                )
                self.assertGreaterEqual(
                    allocation["urllc"],
                    5,
                )
                self.assertEqual(
                    allocation["embb"]
                    + allocation["urllc"],
                    50,
                )

    def test_non_divisible_queue_ratio(self):
        state = make_queue_state(1234, 5678)
        action = self.scheduler.select_action(
            state,
            QUEUE_BASED_CONFIG,
        )
        allocation = action["rb_allocation"]
        self.assertEqual(
            allocation["embb"]
            + allocation["urllc"],
            50,
        )
        self.assertGreaterEqual(allocation["embb"], 5)
        self.assertGreaterEqual(allocation["urllc"], 5)
        self.assertGreater(
            allocation["urllc"],
            allocation["embb"],
        )

    def test_action_has_expected_metadata(self):
        state = make_queue_state(
            3000,
            1000,
            time_slot=7,
        )
        action = self.scheduler.select_action(
            state,
            QUEUE_BASED_CONFIG,
        )
        self.assertEqual(action["schema_version"], "1.0.0")
        self.assertEqual(
            action["request_id"],
            "stable_load-42-7",
        )
        self.assertEqual(action["time_slot"], 7)
        self.assertEqual(
            action["scheduler"],
            "queue_based",
        )
        self.assertEqual(action["action_id"], 1)

    def test_explicit_request_id_is_preserved(self):
        state = make_queue_state(3000, 1000)
        action = self.scheduler.select_action(
            state,
            QUEUE_BASED_CONFIG,
            request_id="tv5-queue-request-001",
        )
        self.assertEqual(
            action["request_id"],
            "tv5-queue-request-001",
        )

    def test_action_passes_validator(self):
        state = make_queue_state(3000, 1000)
        action = self.scheduler.select_action(
            state,
            QUEUE_BASED_CONFIG,
        )
        validated_action = validate_action(
            action=action,
            state=state,
            total_rb=50,
            require_all_rb=True,
        )
        self.assertEqual(validated_action, action)

    def test_invalid_minimum_rb_config_is_rejected(self):
        invalid_config = deepcopy(QUEUE_BASED_CONFIG)
        invalid_config["queue_based"]["min_rb_embb"] = 30
        invalid_config["queue_based"]["min_rb_urllc"] = 30
        state = make_queue_state(1000, 1000)

        with self.assertRaises(ValueError):
            self.scheduler.select_action(
                state,
                invalid_config,
            )

    def test_zero_total_rb_is_rejected(self):
        invalid_config = deepcopy(QUEUE_BASED_CONFIG)
        invalid_config["common"]["total_rb"] = 0
        invalid_config["queue_based"]["min_rb_embb"] = 0
        invalid_config["queue_based"]["min_rb_urllc"] = 0
        state = make_queue_state(1000, 1000)

        with self.assertRaises(ValueError):
            self.scheduler.select_action(
                state,
                invalid_config,
            )

    def test_negative_queue_is_rejected(self):
        state = make_queue_state(-1, 1000)

        with self.assertRaises(ValueError):
            self.scheduler.select_action(
                state,
                QUEUE_BASED_CONFIG,
            )

    def test_missing_queue_bits_is_rejected(self):
        state = make_queue_state(1000, 1000)
        del state["embb"]["queue_bits"]

        with self.assertRaises(ValueError):
            self.scheduler.select_action(
                state,
                QUEUE_BASED_CONFIG,
            )

    def test_boolean_queue_is_rejected(self):
        state = make_queue_state(1000, 1000)
        state["embb"]["queue_bits"] = True

        with self.assertRaises(ValueError):
            self.scheduler.select_action(
                state,
                QUEUE_BASED_CONFIG,
            )


if __name__ == "__main__":
    unittest.main()
