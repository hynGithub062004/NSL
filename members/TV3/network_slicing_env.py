"""Gymnasium adapter to TV1 RANSimulator, with auditable episode seeds."""
from __future__ import annotations

import sys
from pathlib import Path

import gymnasium as gym
import numpy as np
from gymnasium import spaces

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from members.TV1.src.ran import RANSimulator

ACTION_RATIOS = ((0.2, 0.8), (0.4, 0.6), (0.5, 0.5), (0.6, 0.4), (0.8, 0.2))


def make_action(action_id: int, state: dict, total_rb: int,
                request_id: str | None = None) -> dict:
    idx = int(action_id)
    if idx not in range(len(ACTION_RATIOS)):
        raise ValueError(f"Invalid action_id: {idx}")
    embb_rb = round(total_rb * ACTION_RATIOS[idx][0])
    return {
        "schema_version": "1.0.0",
        "request_id": request_id or f'req-{int(state["time_slot"]):06d}',
        "time_slot": int(state["time_slot"]),
        "scheduler": "dqn",
        "action_id": idx,
        "rb_allocation": {"embb": embb_rb, "urllc": total_rb - embb_rb},
    }


class NetworkSlicingEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(
        self,
        config_path: str = "members/TV1/configs/urllc_burst.yaml",
        *,
        episode_seed_base: int | None = None,
        episode_seed_stride: int = 1,
        episode_seeds: tuple[int, ...] | None = None,
    ):
        super().__init__()
        if episode_seed_base is not None and episode_seeds is not None:
            raise ValueError("Use episode_seed_base OR episode_seeds, not both")
        if episode_seed_stride < 1:
            raise ValueError("episode_seed_stride must be >= 1")
        if episode_seeds is not None and len(episode_seeds) == 0:
            raise ValueError("episode_seeds cannot be empty")
        self.episode_seed_base = episode_seed_base
        self.episode_seed_stride = episode_seed_stride
        self.episode_seeds = tuple(episode_seeds) if episode_seeds is not None else None
        self.episode_index = 0
        self.actual_episode_seeds: list[int] = []

        path = Path(config_path)
        if not path.is_absolute():
            path = ROOT / path
        self.ran = RANSimulator.from_yaml(path)
        self.action_space = spaces.Discrete(len(ACTION_RATIOS))
        self.observation_space = spaces.Box(
            low=0.0, high=1.0, shape=(5,), dtype=np.float32
        )
        self._state = self.ran.get_state()

    @staticmethod
    def _extract_obs(state: dict) -> np.ndarray:
        e, u = state["embb"], state["urllc"]
        return np.asarray([
            min(float(e["queue_bits"]) / 250000.0, 1.0),
            float(e["cqi"]) / 15.0,
            min(float(u["queue_bits"]) / 100000.0, 1.0),
            float(u["cqi"]) / 15.0,
            min(float(u["oldest_packet_delay_ms"]) / float(u["deadline_ms"]), 1.0),
        ], dtype=np.float32)

    def reset(self, *, seed=None, options=None):
        # A configured training schedule takes precedence over SB3's model seed.
        if self.episode_seed_base is not None:
            effective_seed = int(self.episode_seed_base) + (
                self.episode_index * int(self.episode_seed_stride)
            )
        elif self.episode_seeds is not None:
            effective_seed = int(
                self.episode_seeds[self.episode_index % len(self.episode_seeds)]
            )
        elif seed is not None:
            effective_seed = int(seed)
        else:
            # Preserve explicit legacy semantics for evaluation scripts.
            effective_seed = int(self.ran.config["simulation"]["seed"])

        super().reset(seed=effective_seed)
        self._state = self.ran.reset(seed=effective_seed)
        self.actual_episode_seeds.append(effective_seed)
        self.episode_index += 1
        return self._extract_obs(self._state), {
            "state": self._state,
            "effective_seed": effective_seed,
        }

    def step(self, action):
        if not self.action_space.contains(int(action)):
            raise ValueError(f"Out-of-range action index: {action}")
        payload = make_action(int(action), self._state, self.ran.total_rb)
        transition = self.ran.apply_action(payload)
        kpi = transition["ran_kpi"]
        throughput = min(float(kpi["throughput_e"]) / 20.0, 1.0)
        delay_penalty = min(
            float(kpi["delay_u"]) / float(self._state["urllc"]["deadline_ms"]), 1.0
        )
        reward = (
            throughput - 0.4 * delay_penalty
            - 1.5 * float(kpi["drop_u"])
            - 1.5 * float(kpi["sla_violation"])
        )
        terminated = bool(transition["done"])
        self._state = transition["next_state"]
        obs = (
            np.zeros(self.observation_space.shape, dtype=np.float32)
            if terminated else self._extract_obs(self._state)
        )
        return obs, float(reward), terminated, False, {
            "ran_kpi": kpi, "action": payload,
        }
