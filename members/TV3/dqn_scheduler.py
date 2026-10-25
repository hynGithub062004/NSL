
"""
TV3 - DQN Scheduler Adapter
Network Slicing - OFDMA - DQN - SRv6

Contract: 1.0.0

Input:
    State from TV1 RANSimulator

Output:
    Action compatible with TV1/TV5

Does not:
    - Generate traffic
    - Modify queues
    - Apply RB allocations
    - Calculate RAN KPI
    - Control SRv6
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import math

import numpy as np
from stable_baselines3 import DQN

from members.TV3.network_slicing_env import (
    NetworkSlicingEnv,
    make_action,
)


TV3_DIR = Path(__file__).resolve().parent

DEFAULT_MODEL = (
    TV3_DIR / "models" / "dqn_v2_best.zip"
)

SCHEMA_VERSION = "1.0.0"


class DQNScheduler:
    """
    Adapter for integration with TV5 Orchestrator.

    Loads a trained DQN checkpoint and returns
    a Contract 1.0.0 RB allocation Action.
    """

    def __init__(
        self,
        model_path: str | Path = DEFAULT_MODEL,
        total_rb: int = 50,
    ):

        self.model_path = Path(model_path)

        if not self.model_path.is_file():
            raise FileNotFoundError(
                f"DQN checkpoint not found: {self.model_path}"
            )

        if type(total_rb) is not int or total_rb <= 0:
            raise ValueError("total_rb must be positive integer")

        self.total_rb = total_rb

        # Load once, not for every request.
        self.model = DQN.load(
            str(self.model_path),
            device="cpu"
        )

        expected_shape = (5,)

        if self.model.observation_space.shape != expected_shape:
            raise ValueError(
                "Checkpoint observation shape mismatch: "
                f"expected={expected_shape}, "
                f"actual={self.model.observation_space.shape}"
            )

        if self.model.action_space.n != 5:
            raise ValueError(
                "DQN checkpoint must use Discrete(5)"
            )

    @staticmethod
    def validate_state(state: dict[str, Any]) -> None:

        if not isinstance(state, dict):
            raise TypeError("State must be a dictionary")

        if state.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Invalid State schema_version")

        for field in (
            "time_slot",
            "scenario_id",
            "seed",
            "embb",
            "urllc",
        ):
            if field not in state:
                raise ValueError(
                    f"Missing State field: {field}"
                )

        if (
            type(state["time_slot"]) is not int
            or state["time_slot"] < 0
        ):
            raise ValueError("Invalid time_slot")

        if not isinstance(state["scenario_id"], str) or not state["scenario_id"]:
            raise ValueError("Invalid scenario_id")

        if type(state["seed"]) is not int:
            raise ValueError("Invalid seed")

        embb = state["embb"]
        urllc = state["urllc"]

        if not isinstance(embb, dict) or not isinstance(urllc, dict):
            raise ValueError("Invalid slice data")

        for name, slc in (("embb", embb), ("urllc", urllc)):

            queue_bits = slc.get("queue_bits")
            cqi = slc.get("cqi")

            if (
                type(queue_bits) is not int
                or queue_bits < 0
            ):
                raise ValueError(
                    f"Invalid {name}.queue_bits"
                )

            if (
                type(cqi) is not int
                or not 1 <= cqi <= 15
            ):
                raise ValueError(
                    f"Invalid {name}.cqi"
                )

        if (
            type(urllc.get("queue_packets")) is not int
            or urllc["queue_packets"] < 0
        ):
            raise ValueError("Invalid urllc.queue_packets")

        for name in (
            "oldest_packet_delay_ms",
            "deadline_ms",
        ):
            value = urllc.get(name)

            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"Invalid urllc.{name}")

            if name == "deadline_ms" and value <= 0:
                raise ValueError("deadline_ms must be positive")

            if name == "oldest_packet_delay_ms" and value < 0:
                raise ValueError("oldest delay must be non-negative")

    def predict(
        self,
        state: dict[str, Any],
        request_id: str,
    ) -> dict[str, Any]:
        """
        Returns DQN Action without modifying RAN state.
        """

        self.validate_state(state)

        if not isinstance(request_id, str) or not request_id:
            raise ValueError("request_id must be nonempty string")

        observation = NetworkSlicingEnv._extract_obs(state)

        if (
            observation.shape != (5,)
            or observation.dtype != np.float32
            or not np.isfinite(observation).all()
        ):
            raise ValueError("Invalid observation")

        action_id, _ = self.model.predict(
            observation,
            deterministic=True
        )

        action = make_action(
            action_id=int(action_id),
            state=state,
            total_rb=self.total_rb,
            request_id=request_id,
        )

        if action["schema_version"] != SCHEMA_VERSION:
            raise RuntimeError("Invalid Action contract")

        allocation = action["rb_allocation"]

        if (
            allocation["embb"] < 0
            or allocation["urllc"] < 0
            or allocation["embb"] + allocation["urllc"]
            != self.total_rb
        ):
            raise RuntimeError("Invalid RB allocation")

        return action


# ===================================================
# Manual smoke test
# ===================================================

def main():

    scheduler = DQNScheduler()

    sample_state = {
        "schema_version": "1.0.0",
        "time_slot": 125,
        "scenario_id": "urllc_burst",
        "seed": 42,
        "embb": {
            "queue_bits": 238400,
            "cqi": 11,
        },
        "urllc": {
            "queue_packets": 18,
            "queue_bits": 46080,
            "cqi": 7,
            "oldest_packet_delay_ms": 4.0,
            "deadline_ms": 5.0,
        },
    }

    action = scheduler.predict(
        state=sample_state,
        request_id="req-000125"
    )

    import json

    print(json.dumps(
        action,
        indent=2,
        ensure_ascii=False
    ))


if __name__ == "__main__":
    main()
