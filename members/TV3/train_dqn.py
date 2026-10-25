from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt

from stable_baselines3 import DQN
from stable_baselines3.common.callbacks import EvalCallback
from stable_baselines3.common.env_checker import check_env
from stable_baselines3.common.monitor import Monitor


# ===================================================
# 1. DUONG DAN CHUNG
# ===================================================

TV3_DIR = Path(__file__).resolve().parent
ROOT = TV3_DIR.parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from members.TV3.network_slicing_env import NetworkSlicingEnv

CONFIG_PATH = "members/TV1/configs/urllc_burst.yaml"

MODEL_DIR = TV3_DIR / "models"
RESULT_DIR = TV3_DIR / "results" / "training_v2"
FIGURE_DIR = TV3_DIR / "figures"

TEMP_MODEL_DIR = RESULT_DIR / "checkpoint_temp"

for folder in (
    MODEL_DIR,
    RESULT_DIR,
    FIGURE_DIR,
    TEMP_MODEL_DIR,
):
    folder.mkdir(parents=True, exist_ok=True)


# ===================================================
# 2. HAM GHI CSV
# ===================================================

def save_csv(path, columns, rows):
    with path.open(
        "w",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        writer = csv.writer(file)
        writer.writerow(columns)
        writer.writerows(rows)

    print(f"Created: {path}")


# ===================================================
# 3. DQN CO GHI TRAINING LOSS
# ===================================================

class LoggedDQN(DQN):
    """
    Ghi loss sau moi lan DQN thuc hien gradient update.
    Khong thay doi thuat toan DQN cua SB3.
    """

    def __init__(self, *args, **kwargs):
        self.loss_history = []
        super().__init__(*args, **kwargs)

    def train(self, gradient_steps, batch_size=100):

        super().train(
            gradient_steps=gradient_steps,
            batch_size=batch_size
        )

        loss = self.logger.name_to_value.get(
            "train/loss"
        )

        if loss is not None and np.isfinite(loss):

            self.loss_history.append([
                int(self.num_timesteps),
                int(self._n_updates),
                float(loss)
            ])


# ===================================================
# 4. MOI TRUONG EVALUATION RIENG
# ===================================================

class HeldoutEvalEnv(NetworkSlicingEnv):
    """
    Su dung evaluation seed 101.
    Khong dung benchmark seeds 42, 43, 44.
    """

    def reset(self, *, seed=None, options=None):

        if seed is None:
            seed = 101

        return super().reset(
            seed=seed,
            options=options
        )


# ===================================================
# 5. DOC TRAINING REWARD TU MONITOR
# ===================================================

def read_training_reward():

    monitor_file = RESULT_DIR / "train.monitor.csv"

    if not monitor_file.exists():
        raise FileNotFoundError(monitor_file)

    rows = []
    total_steps = 0

    with monitor_file.open(
        "r",
        encoding="utf-8"
    ) as file:

        # Dong dau tien cua Monitor la metadata JSON.
        next(file)

        reader = csv.DictReader(file)

        for episode, row in enumerate(reader, start=1):

            episode_reward = float(row["r"])
            episode_length = int(row["l"])

            total_steps += episode_length

            rows.append([
                episode,
                total_steps,
                episode_reward,
                episode_length
            ])

    return rows


# ===================================================
# 6. VE TRAINING REWARD
# ===================================================

def plot_training_reward(rows):

    if not rows:
        raise RuntimeError("Khong co training reward")

    steps = np.array(
        [r[1] for r in rows],
        dtype=float
    )

    rewards = np.array(
        [r[2] for r in rows],
        dtype=float
    )

    window = min(10, len(rewards))

    moving_average = np.array([
        np.mean(
            rewards[max(0, i - window + 1):i + 1]
        )
        for i in range(len(rewards))
    ])

    fig, ax = plt.subplots(figsize=(10, 6))

    ax.plot(
        steps,
        rewards,
        alpha=0.35,
        label="Episode Reward"
    )

    ax.plot(
        steps,
        moving_average,
        linewidth=2,
        label="Moving Average"
    )

    ax.set_title("DQN v2 - Training Reward")
    ax.set_xlabel("Training Timesteps")
    ax.set_ylabel("Episode Reward")

    ax.grid(True, alpha=0.3)
    ax.legend()

    fig.tight_layout()

    output = FIGURE_DIR / "training_reward.png"
    fig.savefig(output, dpi=300)
    plt.close(fig)

    print(f"Created: {output}")


# ===================================================
# 7. VE TRAINING LOSS
# ===================================================

def plot_training_loss(rows):

    if not rows:
        raise RuntimeError(
            "Khong ghi duoc Training Loss"
        )

    steps = np.array(
        [r[0] for r in rows],
        dtype=float
    )

    losses = np.array(
        [r[2] for r in rows],
        dtype=float
    )

    fig, ax = plt.subplots(figsize=(10, 6))

    ax.plot(
        steps,
        losses,
        linewidth=1.2,
        label="DQN Training Loss"
    )

    ax.set_title("DQN v2 - Training Loss")
    ax.set_xlabel("Training Timesteps")
    ax.set_ylabel("Loss")

    ax.grid(True, alpha=0.3)
    ax.legend()

    fig.tight_layout()

    output = FIGURE_DIR / "training_loss.png"
    fig.savefig(output, dpi=300)
    plt.close(fig)

    print(f"Created: {output}")


# ===================================================
# 8. XUAT EVALUATION REWARD
# ===================================================

def export_evaluation_reward():

    path = RESULT_DIR / "evaluations.npz"

    if not path.exists():
        raise FileNotFoundError(path)

    with np.load(
        path,
        allow_pickle=False
    ) as data:

        timesteps = np.asarray(data["timesteps"])
        rewards = np.asarray(data["results"])

    if rewards.ndim != 2:
        raise ValueError("Invalid evaluation rewards")

    if rewards.shape[0] != len(timesteps):
        raise ValueError("Timesteps mismatch")

    mean = np.mean(rewards, axis=1)

    std = np.std(
        rewards,
        axis=1,
        ddof=1 if rewards.shape[1] > 1 else 0
    )

    rows = []

    for i, step in enumerate(timesteps):

        rows.append([
            int(step),
            int(rewards.shape[1]),
            round(float(mean[i]), 6),
            round(float(std[i]), 6),
            round(float(np.min(rewards[i])), 6),
            round(float(np.max(rewards[i])), 6)
        ])

    save_csv(
        RESULT_DIR / "evaluation_reward.csv",
        [
            "timesteps",
            "evaluation_episodes",
            "mean_reward",
            "std_reward",
            "min_reward",
            "max_reward"
        ],
        rows
    )

    fig, ax = plt.subplots(figsize=(10, 6))

    ax.plot(
        timesteps,
        mean,
        marker="o",
        label="Mean Evaluation Reward"
    )

    ax.fill_between(
        timesteps,
        mean - std,
        mean + std,
        alpha=0.2,
        label="Mean +/- 1 Std"
    )

    ax.set_title("DQN v2 - Evaluation Reward")
    ax.set_xlabel("Training Timesteps")
    ax.set_ylabel("Evaluation Episode Reward")

    ax.grid(True, alpha=0.3)
    ax.legend()

    fig.tight_layout()

    output = FIGURE_DIR / "evaluation_reward.png"
    fig.savefig(output, dpi=300)
    plt.close(fig)

    print(f"Created: {output}")

    return len(timesteps)


# ===================================================
# 9. CHUONG TRINH TRAIN
# ===================================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--timesteps",
        type=int,
        default=50000
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=100
    )

    args = parser.parse_args()

    if args.timesteps <= 0:
        raise ValueError("Timesteps phai > 0")

    print("=" * 60)
    print("TV3 - DQN V2 TRAINING WITH LOGGING")
    print("=" * 60)

    print("Config:", CONFIG_PATH)
    print("Train seed:", args.seed)
    print("Eval seed: 101")
    print("Timesteps:", args.timesteps)

    # Kiem tra Gymnasium environment.
    test_env = NetworkSlicingEnv(CONFIG_PATH)
    check_env(test_env, warn=True)
    test_env.close()

    # Monitor ghi reward va length tung episode.
    train_env = Monitor(
        NetworkSlicingEnv(CONFIG_PATH),
        filename=str(RESULT_DIR / "train")
    )

    train_env.reset(seed=args.seed)

    # Evaluation tach biet train.
    eval_env = Monitor(
        HeldoutEvalEnv(CONFIG_PATH)
    )

    callback = EvalCallback(
        eval_env,
        best_model_save_path=str(TEMP_MODEL_DIR),
        log_path=str(RESULT_DIR),
        eval_freq=2500,
        n_eval_episodes=3,
        deterministic=True,
        verbose=1
    )

    # Giu nguyen hyperparameters DQN v2.
    model = LoggedDQN(
        "MlpPolicy",
        train_env,
        seed=args.seed,
        verbose=1,
        learning_rate=1e-3,
        buffer_size=20000,
        learning_starts=1000,
        batch_size=64,
        gamma=0.99,
        target_update_interval=200,
        exploration_fraction=0.3,
        tensorboard_log=None
    )

    print("\nStarting DQN training...")

    model.learn(
        total_timesteps=args.timesteps,
        callback=callback
    )

    # Luu model cuoi vao vi tri tam.
    last_temp = TEMP_MODEL_DIR / "dqn_v2_last.zip"
    model.save(str(last_temp))

    # Kiem tra checkpoint tot nhat.
    best_temp = TEMP_MODEL_DIR / "best_model.zip"

    if not best_temp.exists():
        raise RuntimeError(
            "Chua tao duoc best_model.zip"
        )

    # Lay training reward.
    training_rewards = read_training_reward()

    if not training_rewards:
        raise RuntimeError("Training Reward rong")

    if not model.loss_history:
        raise RuntimeError("Training Loss rong")

    # Xuat CSV.
    save_csv(
        RESULT_DIR / "training_reward.csv",
        [
            "episode",
            "timesteps",
            "episode_reward",
            "episode_length"
        ],
        training_rewards
    )

    save_csv(
        RESULT_DIR / "training_loss.csv",
        [
            "timesteps",
            "gradient_updates",
            "training_loss"
        ],
        model.loss_history
    )

    # Ve bieu do.
    plot_training_reward(training_rewards)
    plot_training_loss(model.loss_history)

    eval_points = export_evaluation_reward()

    # Luu thong tin tai lap thi nghiem.
    manifest = {
        "model": "DQN v2",
        "config": CONFIG_PATH,
        "train_seed": args.seed,
        "evaluation_seed": 101,
        "benchmark_seeds_reserved": [42, 43, 44],
        "timesteps": args.timesteps,
        "eval_freq": 2500,
        "eval_episodes": 3,
        "learning_rate": 0.001,
        "buffer_size": 20000,
        "learning_starts": 1000,
        "batch_size": 64,
        "gamma": 0.99,
        "target_update_interval": 200,
        "exploration_fraction": 0.3,
        "reward_version": "DQN v2 provisional"
    }

    (
        RESULT_DIR / "training_manifest.json"
    ).write_text(
        json.dumps(
            manifest,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    # Chi ghi de checkpoint v2 sau khi train,
    # logging va ve bieu do thanh cong.
    shutil.copy2(
        best_temp,
        MODEL_DIR / "dqn_v2_best.zip"
    )

    shutil.copy2(
        last_temp,
        MODEL_DIR / "dqn_v2_last.zip"
    )

    train_env.close()
    eval_env.close()

    print("\n" + "=" * 60)
    print("DQN V2 TRAINING COMPLETED")
    print("=" * 60)

    print(
        "Training episodes:",
        len(training_rewards)
    )

    print(
        "Loss observations:",
        len(model.loss_history)
    )

    print("Evaluation points:", eval_points)

    print("Best model: models/dqn_v2_best.zip")
    print("Last model: models/dqn_v2_last.zip")

    print("CSV directory:", RESULT_DIR)
    print("Figure directory:", FIGURE_DIR)

    print("\nSUCCESS: Reward and Loss logs created")


if __name__ == "__main__":
    main()
