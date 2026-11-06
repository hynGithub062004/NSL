from __future__ import annotations

import sys
import unittest
from copy import deepcopy
from pathlib import Path


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


from schedulers.action_validator import validate_action
from schedulers.qos_heuristic import QoSHeuristicScheduler


BASE_STATE = {
    "schema_version": "1.0.0",
    "time_slot": 0,
    "scenario_id": "stable_load",
    "seed": 42,
    "embb": {
        "queue_bits": 17_784,
        "cqi": 11,
    },
    "urllc": {
        "queue_packets": 1,
        "queue_bits": 2_560,
        "cqi": 8,
        "oldest_packet_delay_ms": 0.0,
        "deadline_ms": 5.0,
    },
}


QOS_CONFIG = {
    "common": {
        "total_rb": 50,
        "require_all_rb": True,
        "slot_duration_ms": 1.0,
    },
    "qos_heuristic": {
        "action_id": 2,
        "min_rb_embb": 5,
        "min_rb_urllc": 5,
        "embb_queue_weight": 0.70,
        "embb_cqi_weight": 0.30,
        "urllc_queue_weight": 0.45,
        "urllc_urgency_weight": 1.25,
        "urllc_cqi_weight": 0.10,
        "low_cqi_compensation_weight": 0.0,
        "urgency_power": 2.0,
    },
}


def make_state(
    *,
    embb_queue_bits: int = 17_784,
    urllc_queue_bits: int = 2_560,
    embb_cqi: int = 11,
    urllc_cqi: int = 8,
    oldest_delay_ms: float = 0.0,
    deadline_ms: float = 5.0,
    time_slot: int = 0,
) -> dict:
    """Tạo State hợp lệ cho kiểm thử QoS."""

    state = deepcopy(BASE_STATE)

    state["time_slot"] = time_slot
    state["embb"]["queue_bits"] = embb_queue_bits
    state["embb"]["cqi"] = embb_cqi

    state["urllc"]["queue_bits"] = urllc_queue_bits
    state["urllc"]["cqi"] = urllc_cqi
    state["urllc"]["oldest_packet_delay_ms"] = (
        oldest_delay_ms
    )
    state["urllc"]["deadline_ms"] = deadline_ms

    return state


class QoSUrgencyTests(unittest.TestCase):

    def test_empty_urllc_queue_has_zero_urgency(self):
        urgency = QoSHeuristicScheduler._calculate_urgency(
            urllc_queue_bits=0,
            oldest_delay_ms=0.0,
            deadline_ms=5.0,
            slot_duration_ms=1.0,
            urgency_power=2.0,
        )

        self.assertEqual(urgency, 0.0)

    def test_delay_zero_uses_current_slot_opportunity(self):
        urgency = QoSHeuristicScheduler._calculate_urgency(
            urllc_queue_bits=2_560,
            oldest_delay_ms=0.0,
            deadline_ms=5.0,
            slot_duration_ms=1.0,
            urgency_power=2.0,
        )

        self.assertAlmostEqual(urgency, 0.04)

    def test_delay_two_ms_has_expected_urgency(self):
        urgency = QoSHeuristicScheduler._calculate_urgency(
            urllc_queue_bits=2_560,
            oldest_delay_ms=2.0,
            deadline_ms=5.0,
            slot_duration_ms=1.0,
            urgency_power=2.0,
        )

        self.assertAlmostEqual(urgency, 0.36)

    def test_delay_four_ms_reaches_maximum_urgency(self):
        urgency = QoSHeuristicScheduler._calculate_urgency(
            urllc_queue_bits=2_560,
            oldest_delay_ms=4.0,
            deadline_ms=5.0,
            slot_duration_ms=1.0,
            urgency_power=2.0,
        )

        self.assertAlmostEqual(urgency, 1.0)

    def test_urgency_is_clipped_to_one(self):
        urgency = QoSHeuristicScheduler._calculate_urgency(
            urllc_queue_bits=2_560,
            oldest_delay_ms=10.0,
            deadline_ms=5.0,
            slot_duration_ms=1.0,
            urgency_power=2.0,
        )

        self.assertAlmostEqual(urgency, 1.0)


class QoSCQINormalizationTests(unittest.TestCase):

    def test_cqi_fifteen_normalizes_to_one(self):
        normalized = (
            QoSHeuristicScheduler
            ._normalize_cqi_efficiency(15)
        )

        self.assertAlmostEqual(normalized, 1.0)

    def test_cqi_one_is_positive(self):
        normalized = (
            QoSHeuristicScheduler
            ._normalize_cqi_efficiency(1)
        )

        self.assertGreater(normalized, 0.0)
        self.assertLess(normalized, 1.0)

    def test_normalized_cqi_is_strictly_monotonic(self):
        values = [
            QoSHeuristicScheduler
            ._normalize_cqi_efficiency(cqi)
            for cqi in range(1, 16)
        ]

        for previous, current in zip(
            values,
            values[1:],
        ):
            self.assertLess(previous, current)

    def test_cqi_zero_is_rejected(self):
        with self.assertRaises(ValueError):
            QoSHeuristicScheduler._normalize_cqi_efficiency(
                0
            )

    def test_cqi_sixteen_is_rejected(self):
        with self.assertRaises(ValueError):
            QoSHeuristicScheduler._normalize_cqi_efficiency(
                16
            )


class QoSQueueStateTests(unittest.TestCase):

    def setUp(self):
        self.scheduler = QoSHeuristicScheduler()

    def test_zero_queues_use_equal_allocation(self):
        state = make_state(
            embb_queue_bits=0,
            urllc_queue_bits=0,
        )

        action = self.scheduler.select_action(
            state,
            QOS_CONFIG,
        )

        self.assertEqual(
            action["rb_allocation"],
            {
                "embb": 25,
                "urllc": 25,
            },
        )

    def test_only_embb_active_uses_all_rb(self):
        state = make_state(
            embb_queue_bits=10_000,
            urllc_queue_bits=0,
        )

        action = self.scheduler.select_action(
            state,
            QOS_CONFIG,
        )

        self.assertEqual(
            action["rb_allocation"],
            {
                "embb": 50,
                "urllc": 0,
            },
        )

    def test_only_urllc_active_uses_all_rb(self):
        state = make_state(
            embb_queue_bits=0,
            urllc_queue_bits=10_000,
        )

        action = self.scheduler.select_action(
            state,
            QOS_CONFIG,
        )

        self.assertEqual(
            action["rb_allocation"],
            {
                "embb": 0,
                "urllc": 50,
            },
        )

    def test_active_queues_preserve_minimum_and_total(self):
        state = make_state(
            embb_queue_bits=20_000,
            urllc_queue_bits=5_000,
        )

        action = self.scheduler.select_action(
            state,
            QOS_CONFIG,
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


class QoSActionTests(unittest.TestCase):

    def setUp(self):
        self.scheduler = QoSHeuristicScheduler()

    def test_action_has_expected_metadata(self):
        state = make_state(time_slot=7)

        action = self.scheduler.select_action(
            state,
            QOS_CONFIG,
        )

        self.assertEqual(
            action["schema_version"],
            "1.0.0",
        )
        self.assertEqual(
            action["request_id"],
            "stable_load-42-7",
        )
        self.assertEqual(action["time_slot"], 7)
        self.assertEqual(
            action["scheduler"],
            "qos_heuristic",
        )
        self.assertEqual(action["action_id"], 2)

    def test_explicit_request_id_is_preserved(self):
        state = make_state()

        action = self.scheduler.select_action(
            state,
            QOS_CONFIG,
            request_id="tv5-qos-request-001",
        )

        self.assertEqual(
            action["request_id"],
            "tv5-qos-request-001",
        )

    def test_action_passes_validator(self):
        state = make_state()

        action = self.scheduler.select_action(
            state,
            QOS_CONFIG,
        )

        validated = validate_action(
            action=action,
            state=state,
            total_rb=50,
            require_all_rb=True,
        )

        self.assertEqual(validated, action)

    def test_action_is_deterministic(self):
        state = make_state()

        action_1 = self.scheduler.select_action(
            state,
            QOS_CONFIG,
        )
        action_2 = self.scheduler.select_action(
            state,
            QOS_CONFIG,
        )

        self.assertEqual(action_1, action_2)


class QoSStateValidationTests(unittest.TestCase):

    def setUp(self):
        self.scheduler = QoSHeuristicScheduler()

    def test_boolean_queue_is_rejected(self):
        state = make_state()
        state["embb"]["queue_bits"] = True

        with self.assertRaises(ValueError):
            self.scheduler.select_action(
                state,
                QOS_CONFIG,
            )

    def test_negative_queue_is_rejected(self):
        state = make_state(
            embb_queue_bits=-1,
        )

        with self.assertRaises(ValueError):
            self.scheduler.select_action(
                state,
                QOS_CONFIG,
            )

    def test_cqi_below_range_is_rejected(self):
        state = make_state(
            embb_cqi=0,
        )

        with self.assertRaises(ValueError):
            self.scheduler.select_action(
                state,
                QOS_CONFIG,
            )

    def test_cqi_above_range_is_rejected(self):
        state = make_state(
            urllc_cqi=16,
        )

        with self.assertRaises(ValueError):
            self.scheduler.select_action(
                state,
                QOS_CONFIG,
            )

    def test_negative_delay_is_rejected(self):
        state = make_state(
            oldest_delay_ms=-1.0,
        )

        with self.assertRaises(ValueError):
            self.scheduler.select_action(
                state,
                QOS_CONFIG,
            )

    def test_zero_deadline_is_rejected(self):
        state = make_state(
            deadline_ms=0.0,
        )

        with self.assertRaises(ValueError):
            self.scheduler.select_action(
                state,
                QOS_CONFIG,
            )

    def test_missing_queue_bits_is_rejected(self):
        state = make_state()
        del state["urllc"]["queue_bits"]

        with self.assertRaises(ValueError):
            self.scheduler.select_action(
                state,
                QOS_CONFIG,
            )


class QoSConfigValidationTests(unittest.TestCase):

    def setUp(self):
        self.scheduler = QoSHeuristicScheduler()

    def test_zero_total_rb_is_rejected(self):
        config = deepcopy(QOS_CONFIG)
        config["common"]["total_rb"] = 0

        with self.assertRaises(ValueError):
            self.scheduler.select_action(
                make_state(),
                config,
            )

    def test_zero_slot_duration_is_rejected(self):
        config = deepcopy(QOS_CONFIG)
        config["common"]["slot_duration_ms"] = 0.0

        with self.assertRaises(ValueError):
            self.scheduler.select_action(
                make_state(),
                config,
            )

    def test_minimum_total_above_total_rb_is_rejected(
        self,
    ):
        config = deepcopy(QOS_CONFIG)
        config["qos_heuristic"]["min_rb_embb"] = 30
        config["qos_heuristic"]["min_rb_urllc"] = 30

        with self.assertRaises(ValueError):
            self.scheduler.select_action(
                make_state(),
                config,
            )

    def test_negative_weight_is_rejected(self):
        config = deepcopy(QOS_CONFIG)
        config[
            "qos_heuristic"
        ][
            "urllc_urgency_weight"
        ] = -1.0

        with self.assertRaises(ValueError):
            self.scheduler.select_action(
                make_state(),
                config,
            )


if __name__ == "__main__":
    unittest.main()