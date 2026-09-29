import sys
import os
import csv
from stable_baselines3 import DQN

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

from network_slicing_env import NetworkSlicingEnv

def main():
    model_path = "TV3/models/dqn_best.zip"
    if not os.path.exists(model_path):
        print(f"Không tìm thấy file checkpoint tại {model_path}. Vui lòng chạy train_dqn.py trước!")
        return

    print("Đang nạp mô hình DQN đã huấn luyện...")
    model = DQN.load(model_path)

    env = NetworkSlicingEnv(config_path="configs/urllc_burst.yaml")
    obs, _ = env.reset(seed=42)
    
    done = False
    total_reward = 0.0
    steps = 0

    print("Bắt đầu chạy đánh giá mô hình (Evaluation)...")
    while not done:
        # Dự đoán action theo chính sách deterministic đã học
        action, _states = model.predict(obs, deterministic=True)
        obs, reward, done, truncated, info = env.step(action)
        total_reward += reward
        steps += 1

    print(f"Đánh giá hoàn tất sau {steps} slots!")
    print(f"Tổng phần thưởng thu được (Total Reward): {total_reward:.2f}")

if __name__ == "__main__":
    main()