"""Thin adapter TV3 can wrap with gymnasium.Env without rebuilding the RAN."""

from __future__ import annotations

from ran import RANSimulator
from ran.schemas import SCHEMA_VERSION


class TV3EnvAdapter:
    def __init__(self, config_path: str, action_table: list[tuple[int, int]]):
        self.ran = RANSimulator.from_yaml(config_path)
        self.action_table = action_table

    @staticmethod
    def observation(state: dict) -> list[float]:
        return [
            float(state["embb"]["queue_bits"]),
            float(state["embb"]["cqi"]),
            float(state["urllc"]["queue_packets"]),
            float(state["urllc"]["queue_bits"]),
            float(state["urllc"]["cqi"]),
            float(state["urllc"]["oldest_packet_delay_ms"]),
        ]

    def reset(self, seed: int | None = None) -> list[float]:
        return self.observation(self.ran.reset(seed))

    def step(self, action_id: int) -> tuple[list[float] | None, float, bool, dict]:
        embb_rb, urllc_rb = self.action_table[action_id]
        action = {
            "schema_version": SCHEMA_VERSION,
            "request_id": f"tv3-{self.ran.time_slot:06d}",
            "time_slot": self.ran.time_slot,
            "scheduler": "dqn",
            "action_id": action_id,
            "rb_allocation": {"embb": embb_rb, "urllc": urllc_rb},
        }
        transition = self.ran.apply_action(action)
        kpi = transition["ran_kpi"]
        reward = (
            kpi["throughput_e"]
            - 10.0 * kpi["sla_violation"]
            - 2.0 * kpi["drop_u"]
            + kpi["fairness"]
        )
        next_observation = (
            None
            if transition["next_state"] is None
            else self.observation(transition["next_state"])
        )
        return next_observation, reward, transition["done"], transition

