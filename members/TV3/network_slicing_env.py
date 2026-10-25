"""TV3 Gymnasium adapter around the shared TV1 RANSimulator (Contract 1.0.0)."""
from __future__ import annotations

import sys
from pathlib import Path
import gymnasium as gym
import numpy as np
from gymnasium import spaces

ROOT = Path(__file__).resolve().parents[2] if Path(__file__).resolve().parents[1].name == 'members' else Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from members.TV1.src.ran import RANSimulator

# Keep mapping immutable and identical in training/evaluation/serving.
ACTION_RATIOS = ((.2, .8), (.4, .6), (.5, .5), (.6, .4), (.8, .2))

def make_action(action_id: int, state: dict, total_rb: int, request_id: str | None = None) -> dict:
    """Contract-compatible DQN action. Caller/TV5 owns request_id when integrated."""
    idx = int(action_id)
    if idx not in range(len(ACTION_RATIOS)):
        raise ValueError(f'Invalid action_id: {idx}')
    embb_rb = round(total_rb * ACTION_RATIOS[idx][0])
    return {'schema_version': '1.0.0',
            'request_id': request_id or f'req-{int(state["time_slot"]):06d}',
            'time_slot': int(state['time_slot']), 'scheduler': 'dqn',
            'action_id': idx,
            'rb_allocation': {'embb': embb_rb, 'urllc': total_rb - embb_rb}}

class NetworkSlicingEnv(gym.Env):
    metadata = {'render_modes': []}

    def __init__(self, config_path: str = 'members/TV1/configs/urllc_burst.yaml'):
        super().__init__()
        path = Path(config_path)
        if not path.is_absolute():
            path = ROOT / path
        self.ran = RANSimulator.from_yaml(path)
        self.action_space = spaces.Discrete(len(ACTION_RATIOS))
        # Five signals including urgency; bounded, deterministic scaling.
        self.observation_space = spaces.Box(low=0.0, high=1.0, shape=(5,), dtype=np.float32)
        self._state = self.ran.get_state()

    @staticmethod
    def _extract_obs(state: dict) -> np.ndarray:
        e, u = state['embb'], state['urllc']
        return np.asarray([
            min(float(e['queue_bits']) / 250000.0, 1.0),
            float(e['cqi']) / 15.0,
            min(float(u['queue_bits']) / 100000.0, 1.0),
            float(u['cqi']) / 15.0,
            min(float(u['oldest_packet_delay_ms']) / float(u['deadline_ms']), 1.0),
        ], dtype=np.float32)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._state = self.ran.reset(seed=seed)
        return self._extract_obs(self._state), {'state': self._state}

    def step(self, action):
        if not self.action_space.contains(int(action)):
            raise ValueError(f'Out-of-range action index: {action}')
        payload = make_action(int(action), self._state, self.ran.total_rb)
        transition = self.ran.apply_action(payload)
        kpi = transition['ran_kpi']
        # v2 reward proposal: bounded components; benchmark before adopting officially.
        throughput = min(float(kpi['throughput_e']) / 20.0, 1.0)
        delay_penalty = min(float(kpi['delay_u']) / float(self._state['urllc']['deadline_ms']), 1.0)
        reward = (throughput - 0.4 * delay_penalty
                  - 1.5 * float(kpi['drop_u']) - 1.5 * float(kpi['sla_violation']))
        terminated = bool(transition['done'])
        self._state = transition['next_state']
        # Gymnasium still requires an observation at terminal transition.
        obs = np.zeros(self.observation_space.shape, dtype=np.float32) if terminated else self._extract_obs(self._state)
        return obs, float(reward), terminated, False, {'ran_kpi': kpi, 'action': payload}
