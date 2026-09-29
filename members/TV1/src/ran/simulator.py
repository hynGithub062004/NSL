"""Single source of truth for TV1 traffic, queues, CQI and RAN KPI."""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import platform
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
        self.completed_delay_log_ms: list[float] = []
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
        self.completed_delay_log_ms.clear()
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
        self.completed_delay_log_ms.extend(completed_delays)
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
        (output / "run_summary.json").write_text(
            json.dumps(self.build_run_summary(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (output / "run_manifest.json").write_text(
            json.dumps(self.build_run_manifest(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _safe_ratio(numerator: float, denominator: float) -> float:
        return numerator / denominator if denominator > 0 else 0.0

    @staticmethod
    def _nearest_rank(values: list[float], percentile: float) -> float:
        """Return a deterministic nearest-rank percentile for a non-empty sample."""
        if not values:
            return 0.0
        ordered = sorted(values)
        rank = max(1, math.ceil(percentile * len(ordered)))
        return float(ordered[min(rank, len(ordered)) - 1])

    def build_run_summary(self) -> dict:
        """Aggregate raw counters without averaging per-slot ratios."""
        arrived_packets = sum(row["urllc_arrival_packets"] for row in self.traffic_log)
        arrived_embb_bits = sum(row["embb_arrival_bits"] for row in self.traffic_log)
        arrived_urllc_bits = sum(row["urllc_arrival_bits"] for row in self.traffic_log)
        completed_packets = sum(row["completed_urllc_packets"] for row in self.metrics_log)
        dropped_packets = sum(row["dropped_urllc_packets"] for row in self.metrics_log)
        unresolved_packets = self.urllc_queue.packet_count
        served_embb_bits = sum(row["served_embb_bits"] for row in self.metrics_log)
        served_urllc_bits = sum(row["served_urllc_bits"] for row in self.metrics_log)
        late_completed = sum(
            delay > float(self.config["urllc"]["deadline_ms"])
            for delay in self.completed_delay_log_ms
        )
        processed_slots = len(self.metrics_log)
        duration_seconds = processed_slots * self.slot_duration_ms / 1000.0
        resolved_packets = completed_packets + dropped_packets
        conservation_total = completed_packets + dropped_packets + unresolved_packets
        delays = self.completed_delay_log_ms

        return {
            "schema_version": SCHEMA_VERSION,
            "scenario_id": self.scenario_id,
            "seed": self.seed,
            "status": "complete" if self.done else "partial",
            "processed_slots": processed_slots,
            "slot_duration_ms": self.slot_duration_ms,
            "simulated_duration_ms": processed_slots * self.slot_duration_ms,
            "urllc_packet_counters": {
                "arrived": arrived_packets,
                "completed": completed_packets,
                "dropped": dropped_packets,
                "late_completed": late_completed,
                "unresolved_at_end": unresolved_packets,
                "conservation_ok": arrived_packets == conservation_total,
            },
            "urllc_run_rates": {
                "completion_rate": round(self._safe_ratio(completed_packets, arrived_packets), 6),
                "drop_rate_total": round(self._safe_ratio(dropped_packets, arrived_packets), 6),
                "unresolved_rate": round(self._safe_ratio(unresolved_packets, arrived_packets), 6),
                "resolved_drop_rate": round(self._safe_ratio(dropped_packets, resolved_packets), 6),
            },
            "completed_urllc_delay_ms": {
                "sample_count": len(delays),
                "mean": round(self._safe_ratio(sum(delays), len(delays)), 6),
                "p50_nearest_rank": round(self._nearest_rank(delays, 0.50), 6),
                "p95_nearest_rank": round(self._nearest_rank(delays, 0.95), 6),
                "max": round(max(delays), 6) if delays else 0.0,
            },
            "traffic_and_service": {
                "arrived_embb_bits": arrived_embb_bits,
                "arrived_urllc_bits": arrived_urllc_bits,
                "served_embb_bits": served_embb_bits,
                "served_urllc_bits": served_urllc_bits,
                "offered_embb_mbps": round(
                    self._safe_ratio(arrived_embb_bits, duration_seconds) / 1_000_000.0, 6
                ),
                "offered_urllc_mbps": round(
                    self._safe_ratio(arrived_urllc_bits, duration_seconds) / 1_000_000.0, 6
                ),
                "served_embb_mbps": round(
                    self._safe_ratio(served_embb_bits, duration_seconds) / 1_000_000.0, 6
                ),
                "served_urllc_mbps": round(
                    self._safe_ratio(served_urllc_bits, duration_seconds) / 1_000_000.0, 6
                ),
            },
            "aggregation_rules": {
                "drop_rate_total": "sum(dropped_urllc_packets) / sum(urllc_arrival_packets)",
                "resolved_drop_rate": "sum(dropped) / (sum(completed) + sum(dropped))",
                "delay_population": "completed URLLC packets only; dropped packets are excluded",
                "percentile_method": "nearest rank",
            },
        }

    def build_run_manifest(self) -> dict:
        """Return reproducibility metadata and the exact model assumptions."""
        config_text = json.dumps(
            self.config, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        config_sha256 = hashlib.sha256(config_text.encode("utf-8")).hexdigest()
        action_trace = [
            {
                "scheduler": row["action"]["scheduler"],
                "action_id": row["action"]["action_id"],
                "rb_allocation": row["action"]["rb_allocation"],
            }
            for row in self.transition_log
        ]
        run_material = json.dumps(
            {"config_sha256": config_sha256, "seed": self.seed, "actions": action_trace},
            sort_keys=True,
            separators=(",", ":"),
        )
        run_id = hashlib.sha256(run_material.encode("utf-8")).hexdigest()[:16]
        algorithms = sorted({row["algorithm"] for row in self.metrics_log})
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "config_sha256": config_sha256,
            "scenario_id": self.scenario_id,
            "seed": self.seed,
            "python_version": platform.python_version(),
            "processed_slots": len(self.metrics_log),
            "algorithms": algorithms,
            "model": {
                "capacity_bits": "floor(RB * 168 * CQI_efficiency * 0.75)",
                "cqi_source": "3GPP TS 38.214 Table 5.2.2.1-2 (CQI Table 1)",
                "resource_grid": "168 gross RE per RB-slot = 12 subcarriers * 14 symbols",
                "overhead_factor": self.config["radio"]["overhead_factor"],
                "deadline_policy": (
                    "service first; completion at delay <= deadline is on time; "
                    "an unfinished packet is dropped when age reaches deadline"
                ),
            },
            "config": self.config,
        }

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
