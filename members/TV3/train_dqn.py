import sys
import os

# Thêm đường dẫn gốc để nhận diện cấu trúc dự án
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.append(parent_dir)

from stable_baselines3 import DQN
from members.TV3.network_slicing_env import NetworkSlicingEnv

def main():
    print("--- BẮT ĐẦU QUÁ TRÌNH HUẤN LUYỆN DQN (TV3) ---")
    
    # Tạo thư mục lưu checkpoint nằm gọn trong thư mục TV3 của bạn
    os.makedirs(os.path.join(current_dir, "models"), exist_ok=True)
    os.makedirs(os.path.join(current_dir, "results"), exist_ok=True)

    print("Đang khởi tạo môi trường Gymnasium từ TV1...")
    env = NetworkSlicingEnv(config_path="configs/urllc_burst.yaml")

    print("Đang thiết lập mô hình DQN (PyTorch)...")
    model = DQN(
        "MlpPolicy",
        env,
        verbose=1,
        learning_rate=1e-3,
        buffer_size=10000,
        learning_starts=100,
        batch_size=32,
        gamma=0.99,
        device="auto"
    )

    print("Đang tiến hành huấn luyện mô hình (total_timesteps=2000)...")
    model.learn(total_timesteps=2000)

    model_path = os.path.join(current_dir, "models", "dqn_best.zip")
    model.save(model_path)
    print(f"Huấn luyện thành công! Đã lưu checkpoint tại: {model_path}")

if __name__ == "__main__":
    main()