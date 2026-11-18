from __future__ import annotations

import sys
import unittest
from copy import deepcopy
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
TV1_SRC = REPOSITORY_ROOT / "members" / "TV1" / "src"
TV2_SRC = REPOSITORY_ROOT / "members" / "TV2" / "src"

for source_dir in (TV1_SRC, TV2_SRC):
    source_text = str(source_dir)
    if source_text not in sys.path:
        sys.path.insert(0, source_text)


from schedulers.action_validator import validate_action
from schedulers.random_scheduler import RandomScheduler


RANDOM_CONFIG = {
    "common": {
        "total_rb": 50,
        "require_all_rb": True,
    },
    "random": {
        "action_id": 3,
    },
}


def make_state(seed: int = 42, time_slot: int = 0) -> dict:
    return {
        "schema_version": "1.0.0",
        "scenario_id": "stable_load",
        "seed": seed,
        "time_slot": time_slot,
    }


class RandomSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scheduler = RandomScheduler()

    def test_valid_action_preserves_total_rb(self):
        state = make_state(seed=42, time_slot=0)
        action = self.scheduler.select_action(state, RANDOM_CONFIG)

        allocation = action["rb_allocation"]
        self.assertEqual(allocation["embb"] + allocation["urllc"], 50)
        self.assertGreaterEqual(allocation["embb"], 0)
        self.assertGreaterEqual(allocation["urllc"], 0)
        self.assertEqual(action["scheduler"], "random")
        self.assertEqual(action["action_id"], 3)

        validate_action(
            action=action,
            state=state,
            total_rb=50,
            require_all_rb=True,
        )

    def test_same_seed_and_slot_are_reproducible(self):
        state = make_state(seed=42, time_slot=7)
        first = self.scheduler.select_action(
            state,
            RANDOM_CONFIG,
            request_id="request-a",
        )
        second = self.scheduler.select_action(
            state,
            RANDOM_CONFIG,
            request_id="request-b",
        )

        self.assertEqual(
            first["rb_allocation"],
            second["rb_allocation"],
        )
        self.assertNotEqual(first["request_id"], second["request_id"])

    def test_three_seeds_produce_distinct_sequences(self):
        sequences = []
        for seed in (42, 43, 44):
            sequence = []
            for time_slot in range(10):
                state = make_state(seed=seed, time_slot=time_slot)
                action = self.scheduler.select_action(state, RANDOM_CONFIG)
                sequence.append(action["rb_allocation"]["embb"])
            sequences.append(tuple(sequence))

        self.assertEqual(len(set(sequences)), 3)

    def test_all_slots_preserve_total_rb(self):
        for seed in (42, 43, 44):
            for time_slot in range(100):
                with self.subTest(seed=seed, time_slot=time_slot):
                    state = make_state(seed=seed, time_slot=time_slot)
                    action = self.scheduler.select_action(state, RANDOM_CONFIG)
                    allocation = action["rb_allocation"]
                    self.assertEqual(
                        allocation["embb"] + allocation["urllc"],
                        50,
                    )
                    self.assertGreaterEqual(allocation["embb"], 0)
                    self.assertLessEqual(allocation["embb"], 50)
                    self.assertGreaterEqual(allocation["urllc"], 0)
                    self.assertLessEqual(allocation["urllc"], 50)

    def test_invalid_total_rb_is_rejected(self):
        state = make_state()
        config = deepcopy(RANDOM_CONFIG)
        config["common"]["total_rb"] = 0

        with self.assertRaisesRegex(ValueError, "total_rb must be positive"):
            self.scheduler.select_action(state, config)

    def test_negative_seed_is_rejected(self):
        state = make_state(seed=-1)

        with self.assertRaisesRegex(
            ValueError,
            "state.seed must be non-negative",
        ):
            self.scheduler.select_action(state, RANDOM_CONFIG)

    def test_negative_time_slot_is_rejected(self):
        state = make_state(time_slot=-1)

        with self.assertRaisesRegex(
            ValueError,
            "state.time_slot must be non-negative",
        ):
            self.scheduler.select_action(state, RANDOM_CONFIG)


if __name__ == "__main__":
    unittest.main()
