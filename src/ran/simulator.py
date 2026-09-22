"""Single source of truth for TV1 traffic, queues, CQI and RAN KPI."""

from __future__ import annotations

import copy
import csv
import json
import math
from pathlib import Path
from typing import Any

from .config import load_yaml, validate_config
from .cqi import CQIModel
from .metrics import calculate_slot_kpi
from .queue import EmbbQueue, UrllcQueue
from .rb_capacity import capacity_bits
from .schemas import SCHEMA_VERSION, validate_action, validate_kpi, validate_state
from .traffic import TrafficGenerator


class SimulationFinishedError(RuntimeError):
    """Raised when an action is applied after the configured final slot."""


class RANSimulator:
    """Deterministic two-slice RAN environment shared by TV2, TV3 and TV5."""

    def __init__(self, config: dict[str, Any]):
        validate_config(config)
        self.config = copy.deepcopy(config)
        self.embb_queue = EmbbQueue()
        self.urllc_queue = UrllcQueue()
        self.traffic = TrafficGenerator(self.config)
        self.cqi = CQIModel(self.config)
        self.state_log: list[dict] = []
        self.traffic_log: list[dict] = []
        self.cqi_log: list[dict] = []
        self.metrics_log: list[dict] = []
        self.transition_log: list[dict] = []
        self.seed = 0
        self.time_slot = 0
        self.done = False
        self._current_cqi = {"embb": 1, "urllc": 1}
        self.reset()

    @classmethod
    def from_yaml(cls, path: str | Path) -> "RANSimulator":
        return cls(load_yaml(path))

    @property
    def total_rb(self) -> int:
        return int(self.config["radio"]["total_rb"])

    @property
    def slot_duration_ms(self) -> float:
        return float(self.config["simulation"]["slot_duration_ms"])

    @property
    def total_slots(self) -> int:
        return int(self.config["simulation"]["slots"])

    @property
    def scenario_id(self) -> str:
        return str(self.config["scenario"]["id"])

    def reset(self, seed: int | None = None) -> dict:
        self.seed = int(self.config["simulation"]["seed"] if seed is None else seed)
        self.time_slot = 0
        self.done = False
        self.embb_queue.reset()
        self.urllc_queue.reset()
        self.traffic.reset(self.seed)
        self.cqi.reset(self.seed)
        self.state_log.clear()
        self.traffic_log.clear()
        self.cqi_log.clear()
        self.metrics_log.clear()
        self.transition_log.clear()
        self._prepare_slot()
        return self.get_state()

    def _prepare_slot(self) -> None:
        arrival = self.traffic.generate(self.time_slot)
        self.embb_queue.enqueue(arrival.embb_bits)
        self.urllc_queue.enqueue(arrival.urllc_packets)
        self._current_cqi = self.cqi.update()
        self.traffic_log.append(
            {
                "seed": self.seed,
                "scenario_id": self.scenario_id,
                "time_slot": self.time_slot,
                "embb_arrival_bits": arrival.embb_bits,
                "urllc_arrival_packets": len(arrival.urllc_packets),
                "urllc_arrival_bits": sum(p.size_bits for p in arrival.urllc_packets),
            }
        )
        self.cqi_log.append(
            {
                "seed": self.seed,
                "scenario_id": self.scenario_id,
                "time_slot": self.time_slot,
                "embb_cqi": self._current_cqi["embb"],
                "urllc_cqi": self._current_cqi["urllc"],
            }
        )

    def get_state(self) -> dict:
        state = {
            "schema_version": SCHEMA_VERSION,
            "time_slot": self.time_slot,
            "scenario_id": self.scenario_id,
            "seed": self.seed,
            "embb": {
                "queue_bits": self.embb_queue.bits,
                "cqi": self._current_cqi["embb"],
            },
            "urllc": {
                "queue_packets": self.urllc_queue.packet_count,
                "queue_bits": self.urllc_queue.total_bits,
                "cqi": self._current_cqi["urllc"],
                "oldest_packet_delay_ms": self.urllc_queue.oldest_delay_ms,
                "deadline_ms": float(self.config["urllc"]["deadline_ms"]),
            },
        }
        validate_state(state)
        if not self.state_log or self.state_log[-1]["time_slot"] != self.time_slot:
            self.state_log.append(copy.deepcopy(state))
        return copy.deepcopy(state)

    @staticmethod
    def _used_rb(allocated_rb: int, served_bits: int, capacity: int) -> int:
        if allocated_rb == 0 or served_bits == 0 or capacity == 0:
            return 0
        return min(allocated_rb, math.ceil(allocated_rb * served_bits / capacity))

    def apply_action(self, action: dict[str, Any]) -> dict:
        if self.done:
            raise SimulationFinishedError("Simulation has already reached the final slot")
        validate_action(action, self.total_rb, self.time_slot)
        state_before = self.get_state()
        embb_demand = self.embb_queue.bits
        urllc_demand = self.urllc_queue.total_bits
        allocation = action["rb_allocation"]
        embb_capacity = capacity_bits(
            allocation["embb"], self._current_cqi["embb"], self.config["radio"]
        )
        urllc_capacity = capacity_bits(
            allocation["urllc"], self._current_cqi["urllc"], self.config["radio"]
        )
        served_embb = self.embb_queue.serve(embb_capacity)
        urllc_service = self.urllc_queue.serve(urllc_capacity)
        completed_delays = [
            packet.age_ms + self.slot_duration_ms
            for packet in urllc_service.completed_packets
        ]
        dropped = self.urllc_queue.age_and_drop(self.slot_duration_ms)
        used_embb_rb = self._used_rb(allocation["embb"], served_embb, embb_capacity)
        used_urllc_rb = self._used_rb(
            allocation["urllc"], urllc_service.served_bits, urllc_capacity
        )
        kpi = calculate_slot_kpi(
            request_id=action["request_id"],
            seed=self.seed,
            scenario_id=self.scenario_id,
            algorithm=action["scheduler"],
            time_slot=self.time_slot,
            slot_duration_ms=self.slot_duration_ms,
            total_rb=self.total_rb,
            allocated_embb_rb=allocation["embb"],
            allocated_urllc_rb=allocation["urllc"],
            used_embb_rb=used_embb_rb,
            used_urllc_rb=used_urllc_rb,
            embb_demand_bits=embb_demand,
            urllc_demand_bits=urllc_demand,
            served_embb_bits=served_embb,
            served_urllc_bits=urllc_service.served_bits,
            completed_delays_ms=completed_delays,
            dropped_packets=len(dropped),
            deadline_ms=float(self.config["urllc"]["deadline_ms"]),
            schema_version=SCHEMA_VERSION,
        )
        validate_kpi(kpi)
        self.metrics_log.append(copy.deepcopy(kpi))

        self.time_slot += 1
        self.done = self.time_slot >= self.total_slots
        next_state = None
        if not self.done:
            self._prepare_slot()
            next_state = self.get_state()
        transition = {
            "schema_version": SCHEMA_VERSION,
            "request_id": action["request_id"],
            "state": state_before,
            "action": copy.deepcopy(action),
            "ran_kpi": copy.deepcopy(kpi),
            "next_state": next_state,
            "done": self.done,
        }
        self.transition_log.append(copy.deepcopy(transition))
        return transition

    def export_results(self, output_dir: str | Path) -> None:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        self._write_csv(output / "traffic_log.csv", self.traffic_log)
        self._write_csv(output / "cqi_log.csv", self.cqi_log)
        self._write_csv(output / "ran_metrics.csv", self.metrics_log, flatten_units=True)
        (output / "state_log.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in self.state_log),
            encoding="utf-8",
        )
        (output / "transitions.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in self.transition_log),
            encoding="utf-8",
        )
        if self.state_log:
            (output / "state_sample.json").write_text(
                json.dumps(self.state_log[0], ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        if self.transition_log:
            (output / "transition_sample.json").write_text(
                json.dumps(self.transition_log[0], ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    @staticmethod
    def _write_csv(path: Path, rows: list[dict], flatten_units: bool = False) -> None:
        if not rows:
            path.write_text("", encoding="utf-8")
            return
        normalized: list[dict] = []
        for row in rows:
            item = copy.deepcopy(row)
            if flatten_units and isinstance(item.get("units"), dict):
                item["units"] = json.dumps(item["units"], separators=(",", ":"))
            normalized.append(item)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(normalized[0].keys()))
            writer.writeheader()
            writer.writerows(normalized)

