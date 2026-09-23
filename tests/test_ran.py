from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from ran import RANSimulator  # noqa: E402
from ran.packet import Packet  # noqa: E402
from ran.queue import UrllcQueue  # noqa: E402
from ran.rb_capacity import capacity_bits  # noqa: E402
from ran.schemas import SCHEMA_VERSION, SchemaValidationError  # noqa: E402


CONFIG_PATH = PROJECT_ROOT / "configs" / "stable_load.yaml"


def action_for(simulator: RANSimulator, embb: int = 25, urllc: int = 25) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": f"test-{simulator.time_slot:06d}",
        "time_slot": simulator.time_slot,
        "scheduler": "unit_test",
        "action_id": 0,
        "rb_allocation": {"embb": embb, "urllc": urllc},
    }


class RANSimulatorTests(unittest.TestCase):
    def test_all_json_contracts_are_valid_json(self):
        for path in (PROJECT_ROOT / "contracts").glob("*.json"):
            with self.subTest(path=path.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertIsInstance(data, dict)

    def test_same_seed_is_reproducible(self):
        first = RANSimulator.from_yaml(CONFIG_PATH)
        second = RANSimulator.from_yaml(CONFIG_PATH)
        first.reset(99)
        second.reset(99)
        for _ in range(30):
            one = first.apply_action(action_for(first))
            two = second.apply_action(action_for(second))
            self.assertEqual(one, two)

    def test_different_seed_changes_state_sequence(self):
        first = RANSimulator.from_yaml(CONFIG_PATH)
        second = RANSimulator.from_yaml(CONFIG_PATH)
        first.reset(1)
        second.reset(2)
        self.assertNotEqual(first.get_state(), second.get_state())

    def test_queue_never_negative_and_service_never_exceeds_demand(self):
        simulator = RANSimulator.from_yaml(CONFIG_PATH)
        for _ in range(100):
            transition = simulator.apply_action(action_for(simulator))
            kpi = transition["ran_kpi"]
            self.assertGreaterEqual(kpi["served_embb_bits"], 0)
            self.assertGreaterEqual(kpi["served_urllc_bits"], 0)
            self.assertLessEqual(
                kpi["served_embb_bits"], transition["state"]["embb"]["queue_bits"]
            )
            self.assertLessEqual(
                kpi["served_urllc_bits"], transition["state"]["urllc"]["queue_bits"]
            )
            if transition["next_state"]:
                self.assertGreaterEqual(transition["next_state"]["embb"]["queue_bits"], 0)
                self.assertGreaterEqual(transition["next_state"]["urllc"]["queue_bits"], 0)

    def test_invalid_total_rb_is_rejected(self):
        simulator = RANSimulator.from_yaml(CONFIG_PATH)
        with self.assertRaises(SchemaValidationError):
            simulator.apply_action(action_for(simulator, embb=40, urllc=20))

    def test_wrong_slot_is_rejected(self):
        simulator = RANSimulator.from_yaml(CONFIG_PATH)
        action = action_for(simulator)
        action["time_slot"] = 7
        with self.assertRaises(SchemaValidationError):
            simulator.apply_action(action)

    def test_capacity_is_monotonic_in_cqi(self):
        simulator = RANSimulator.from_yaml(CONFIG_PATH)
        capacities = [capacity_bits(10, cqi, simulator.config["radio"]) for cqi in range(1, 16)]
        self.assertEqual(capacities, sorted(capacities))

    def test_kpis_are_finite_and_bounded(self):
        simulator = RANSimulator.from_yaml(CONFIG_PATH)
        transition = simulator.apply_action(action_for(simulator))
        kpi = transition["ran_kpi"]
        for name in ("throughput_e", "delay_u", "drop_u", "sla_violation", "fairness", "rb_utilization"):
            self.assertTrue(math.isfinite(kpi[name]), name)
        for name in ("drop_u", "sla_violation", "fairness", "rb_utilization"):
            self.assertGreaterEqual(kpi[name], 0)
            self.assertLessEqual(kpi[name], 1)

    def test_urllc_deadline_causes_drop_without_rb(self):
        simulator = RANSimulator.from_yaml(CONFIG_PATH)
        simulator.config["urllc"]["arrival_rate_packets_per_slot"] = 10.0
        simulator.config["urllc"]["deadline_ms"] = 1.0
        simulator.traffic.config = simulator.config
        simulator.reset(123)
        transition = simulator.apply_action(action_for(simulator, embb=50, urllc=0))
        self.assertEqual(transition["ran_kpi"]["served_urllc_bits"], 0)
        self.assertEqual(transition["ran_kpi"]["used_urllc_rb"], 0)
        self.assertGreater(transition["ran_kpi"]["dropped_urllc_packets"], 0)

    def test_packet_completed_exactly_at_deadline_is_on_time(self):
        queue = UrllcQueue()
        packet = Packet.create("boundary-complete", 0, 100, 5.0)
        packet.age_ms = 4.0
        queue.enqueue([packet])
        result = queue.serve(100)
        dropped = queue.age_and_drop(1.0)
        completed_delay = result.completed_packets[0].age_ms + 1.0
        self.assertEqual(completed_delay, 5.0)
        self.assertEqual(len(dropped), 0)

    def test_partial_packet_at_deadline_is_dropped(self):
        queue = UrllcQueue()
        packet = Packet.create("boundary-partial", 0, 100, 5.0)
        packet.age_ms = 4.0
        queue.enqueue([packet])
        result = queue.serve(99)
        dropped = queue.age_and_drop(1.0)
        self.assertEqual(result.served_bits, 99)
        self.assertEqual(len(result.completed_packets), 0)
        self.assertEqual([item.packet_id for item in dropped], ["boundary-partial"])

    def test_transition_has_no_future_arrival_leakage(self):
        simulator = RANSimulator.from_yaml(CONFIG_PATH)
        initial_state = simulator.reset(42)
        transition = simulator.apply_action(action_for(simulator))
        self.assertEqual(transition["state"], initial_state)
        self.assertEqual(transition["state"]["time_slot"], 0)
        self.assertEqual(transition["next_state"]["time_slot"], 1)
        expected_embb_queue = (
            initial_state["embb"]["queue_bits"]
            - transition["ran_kpi"]["served_embb_bits"]
            + simulator.traffic_log[1]["embb_arrival_bits"]
        )
        self.assertEqual(transition["next_state"]["embb"]["queue_bits"], expected_embb_queue)

    def test_burst_window_boundaries(self):
        burst_path = PROJECT_ROOT / "configs" / "urllc_burst.yaml"
        simulator = RANSimulator.from_yaml(burst_path)
        self.assertFalse(simulator.traffic._is_burst(49))
        self.assertTrue(simulator.traffic._is_burst(50))
        self.assertTrue(simulator.traffic._is_burst(69))
        self.assertFalse(simulator.traffic._is_burst(70))
        self.assertTrue(simulator.traffic._is_burst(150))

    def test_export_contains_required_files(self):
        simulator = RANSimulator.from_yaml(CONFIG_PATH)
        simulator.apply_action(action_for(simulator))
        with tempfile.TemporaryDirectory() as directory:
            simulator.export_results(directory)
            expected = {
                "traffic_log.csv",
                "cqi_log.csv",
                "ran_metrics.csv",
                "state_log.jsonl",
                "transitions.jsonl",
                "state_sample.json",
                "transition_sample.json",
                "run_summary.json",
                "run_manifest.json",
            }
            self.assertTrue(expected.issubset({p.name for p in Path(directory).iterdir()}))
            sample = json.loads((Path(directory) / "transition_sample.json").read_text())
            self.assertEqual(sample["schema_version"], SCHEMA_VERSION)
            summary = json.loads((Path(directory) / "run_summary.json").read_text())
            counters = summary["urllc_packet_counters"]
            self.assertTrue(counters["conservation_ok"])
            self.assertEqual(
                counters["arrived"],
                counters["completed"] + counters["dropped"] + counters["unresolved_at_end"],
            )


if __name__ == "__main__":
    unittest.main()
