import sys
import os
import gymnasium as gym
from gymnasium import spaces
import numpy as np

# Thiết lập đường dẫn động để Python thực thi lúc chạy
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(current_dir)) # Trỏ về thư mục gốc NSL
tv1_src_dir = os.path.join(parent_dir, 'members', 'TV1', 'src')
if tv1_src_dir not in sys.path:
    sys.path.append(tv1_src_dir)

# Import chuẩn theo kiểu tuyệt đối từ thư mục gốc của TV1 để VS Code / Pylance không báo gợn sóng vàng
from members.TV1.src.ran import RANSimulator

class NetworkSlicingEnv(gym.Env):
    """Môi trường Gymnasium chuẩn cho TV3, tương tác trực tiếp với RANSimulator của TV1."""
    metadata = {"render_modes": ["human"]}

    def __init__(self, config_path="configs/urllc_burst.yaml"):
        super().__init__()
        # Khởi tạo mô phỏng RAN từ cấu hình nằm trong thư mục của TV1
        full_config_path = os.path.join(parent_dir, 'members', 'TV1', config_path)
        self.ran = RANSimulator.from_yaml(full_config_path)
        
        # Không gian hành động rời rạc (Chọn 1 trong 5 tỷ lệ phân bổ RB khác nhau)
        self.action_space = spaces.Discrete(5)
        self.action_mappings = [
            {"embb": 10, "urllc": 40},
            {"embb": 20, "urllc": 30},
            {"embb": 25, "urllc": 25},
            {"embb": 30, "urllc": 20},
            {"embb": 40, "urllc": 10},
        ]

        # Không gian quan sát (Observation Space): eMBB queue, eMBB CQI, URLLC queue, URLLC CQI
        self.observation_space = spaces.Box(
            low=0.0, high=1e8, shape=(4,), dtype=np.float32
        )

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        state = self.ran.reset(seed=seed if seed is not None else 42)
        obs = self._extract_obs(state)
        return obs, {}

    def step(self, action_id):
        rb_alloc = self.action_mappings[action_id]
        
        current_slot = self.ran.current_slot
        action = {
            "schema_version": "1.0.0",
            "request_id": f"req-{current_slot:06d}",
            "time_slot": current_slot,
            "scheduler": "dqn",
            "action_id": int(action_id),
            "rb_allocation": rb_alloc
        }

        transition = self.ran.apply_action(action)
        
        kpi = transition["ran_kpi"]
        throughput_e = kpi.get("throughput_e", 0.0)  # Mbps
        delay_u = kpi.get("delay_u", 0.0)            # ms
        drop_u = kpi.get("drop_u", 0.0)              # tỷ lệ rớt gói [0, 1]
        
        reward = float(throughput_e) - (float(delay_u) * 5.0) - (float(drop_u) * 50.0)

        next_obs = self._extract_obs(transition["next_state"])
        done = transition["done"]
        truncated = False

        return next_obs, reward, done, truncated, {"kpi": kpi}

    def _extract_obs(self, state):
        embb_queue = float(state["embb"]["queue_bits"])
        embb_cqi = float(state["embb"]["cqi"])
        urllc_queue = float(state["urllc"]["queue_packets"])
        urllc_cqi = float(state["urllc"]["cqi"])
        return np.array([embb_queue, embb_cqi, urllc_queue, urllc_cqi], dtype=np.float32)