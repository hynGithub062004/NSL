"""Train DQN v3 with disjoint episode seeds and fixed-seed validation.

Run from NSL root:
  python members/TV3/train_dqn.py --timesteps 50000 --seed 100

Never overwrites DQN v2 files.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import subprocess
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from stable_baselines3 import DQN
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.env_checker import check_env
from stable_baselines3.common.monitor import Monitor

ROOT = Path(__file__).resolve().parents[2]
TV3_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from members.TV3.network_slicing_env import NetworkSlicingEnv

CONFIG = "members/TV1/configs/urllc_burst.yaml"
TRAIN_SEED_BASE = 100000
VALIDATION_SEEDS = (200101, 200102, 200103)
BENCHMARK_SEEDS = (42, 43, 44)
EVAL_FREQ = 2500

RESULT_DIR = TV3_DIR / "results" / "training_v3"
FIGURE_DIR = TV3_DIR / "figures" / "training_v3"
MODEL_DIR = TV3_DIR / "models"

BEST_MODEL = MODEL_DIR / "dqn_v3_best.zip"
LAST_MODEL = MODEL_DIR / "dqn_v3_last.zip"


def write_csv(path: Path, headers: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_head() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


class LoggedDQN(DQN):
    """Record actual training loss without changing DQN."""

    def __init__(self, *args, **kwargs):
        self.loss_history: list[list] = []
        super().__init__(*args, **kwargs)

    def train(self, gradient_steps: int, batch_size: int = 100) -> None:
        super().train(gradient_steps, batch_size)
        loss = self.logger.name_to_value.get("train/loss")

        if loss is not None and np.isfinite(loss):
            self.loss_history.append([
                int(self.num_timesteps),
                int(self._n_updates),
                float(loss),
            ])


class FixedSeedValidation(BaseCallback):
    """Evaluate each checkpoint on three fixed, held-out seeds."""

    def __init__(self, config_path: str, eval_freq: int = EVAL_FREQ):
        super().__init__(verbose=0)
        self.env = NetworkSlicingEnv(config_path)
        self.eval_freq = eval_freq
        self.history: list[dict] = []
        self.best_score = float("-inf")
        self.best_step: int | None = None

    def _on_step(self) -> bool:
        if self.n_calls % self.eval_freq != 0:
            return True

        rewards: list[float] = []

        for val_seed in VALIDATION_SEEDS:
            obs, info = self.env.reset(seed=val_seed)

            if info["effective_seed"] != val_seed:
                raise RuntimeError("Validation seed mismatch")

            done = False
            total_reward = 0.0
            steps = 0

            while not done:
                action, _ = self.model.predict(
                    obs,
                    deterministic=True,
                )

                obs, reward, terminated, truncated, _ = self.env.step(
                    int(action)
                )

                total_reward += float(reward)
                steps += 1
                done = bool(terminated or truncated)

            if steps != 500:
                raise RuntimeError(
                    f"Validation length = {steps}, expected 500"
                )

            rewards.append(total_reward)

        score = statistics.fmean(rewards)
        sd = statistics.stdev(rewards)

        self.history.append({
            "timesteps": int(self.num_timesteps),
            "seeds": list(VALIDATION_SEEDS),
            "rewards": rewards,
            "mean_reward": score,
            "std_reward": sd,
        })

        self.logger.record("eval/mean_reward", score)

        print(
            f"Validation step {self.num_timesteps}: "
            f"mean={score:.4f}, std={sd:.4f}"
        )

        if score > self.best_score:
            self.best_score = score
            self.best_step = int(self.num_timesteps)

            self.model.save(str(BEST_MODEL))

            print(
                f"New best checkpoint: step {self.best_step}"
            )

        return True

    def close(self) -> None:
        self.env.close()


def monitor_episodes(path: Path) -> list[list]:
    if not path.is_file():
        raise FileNotFoundError(path)

    out: list[list] = []
    step = 0

    with path.open("r", encoding="utf-8") as f:
        next(f)

        for index, row in enumerate(csv.DictReader(f), 1):
            length = int(row["l"])
            step += length

            out.append([
                index,
                step,
                float(row["r"]),
                length,
            ])

    return out


def plot_series(
    x,
    y,
    filename: str,
    title: str,
    xlabel: str,
    ylabel: str,
) -> None:
    fig, ax = plt.subplots(figsize=(9, 5))

    ax.plot(x, y)
    ax.set(
        title=title,
        xlabel=xlabel,
        ylabel=ylabel,
    )
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(FIGURE_DIR / filename, dpi=250)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--timesteps",
        type=int,
        default=50000,
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=100,
        help="Algorithm seed, NOT RAN episode seed",
    )

    args = parser.parse_args()

    if args.timesteps < EVAL_FREQ or args.timesteps % EVAL_FREQ:
        parser.error(
            f"--timesteps must be a multiple of {EVAL_FREQ}"
        )

    if len(set(VALIDATION_SEEDS + BENCHMARK_SEEDS)) != 6:
        raise RuntimeError(
            "Validation and benchmark seeds overlap"
        )

    episode_max = TRAIN_SEED_BASE + (args.timesteps // 500) + 2

    if any(
        TRAIN_SEED_BASE <= s <= episode_max
        for s in VALIDATION_SEEDS + BENCHMARK_SEEDS
    ):
        raise RuntimeError(
            "Training range overlaps held-out seeds"
        )

    # Do not overwrite an already completed v3 experiment.
    for output in (
        BEST_MODEL,
        LAST_MODEL,
        RESULT_DIR / "training_manifest.json",
    ):
        if output.exists():
            raise FileExistsError(
                f"v3 output exists; archive it before rerun: {output}"
            )

    # Check compatibility with Gymnasium / Stable-Baselines3.
    test_env = NetworkSlicingEnv(CONFIG)
    try:
        check_env(test_env, warn=True)
    finally:
        test_env.close()

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)

    # A new effective seed for each training episode.
    raw_train = NetworkSlicingEnv(
        CONFIG,
        episode_seed_base=TRAIN_SEED_BASE,
    )

    train_env = Monitor(
        raw_train,
        filename=str(RESULT_DIR / "train"),
    )

    callback = FixedSeedValidation(CONFIG)

    try:
        # Keep the original DQN v2 hyperparameters.
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
            tensorboard_log=None,
        )

        model.learn(
            total_timesteps=args.timesteps,
            callback=callback,
        )

        model.save(str(LAST_MODEL))

        if not BEST_MODEL.is_file() or callback.best_step is None:
            raise RuntimeError(
                "Best checkpoint was not saved"
            )

        episodes = monitor_episodes(
            RESULT_DIR / "train.monitor.csv"
        )

        completed_seeds = raw_train.actual_episode_seeds[
            :len(episodes)
        ]

        if len(completed_seeds) != len(episodes):
            raise RuntimeError(
                "Missing per-episode training seeds"
            )

        if len(set(completed_seeds)) != len(completed_seeds):
            raise RuntimeError(
                "Repeated training seed"
            )

        if set(completed_seeds) & set(
            VALIDATION_SEEDS + BENCHMARK_SEEDS
        ):
            raise RuntimeError(
                "Held-out seed was used to train"
            )

        if not episodes or not callback.history:
            raise RuntimeError(
                "Training or validation log is empty"
            )

        write_csv(
            RESULT_DIR / "training_reward.csv",
            [
                "episode",
                "timesteps",
                "episode_reward",
                "episode_length",
            ],
            episodes,
        )

        write_csv(
            RESULT_DIR / "training_loss.csv",
            [
                "timesteps",
                "gradient_updates",
                "training_loss",
            ],
            model.loss_history,
        )

        write_csv(
            RESULT_DIR / "train_episode_seeds.csv",
            [
                "episode",
                "effective_seed",
            ],
            [
                [i, seed]
                for i, seed in enumerate(completed_seeds, 1)
            ],
        )

        write_csv(
            RESULT_DIR / "validation_rewards.csv",
            [
                "timesteps",
                "seed_200101",
                "seed_200102",
                "seed_200103",
                "mean_reward",
                "std_reward",
            ],
            [
                [
                    row["timesteps"],
                    *row["rewards"],
                    row["mean_reward"],
                    row["std_reward"],
                ]
                for row in callback.history
            ],
        )

        plot_series(
            [r[1] for r in episodes],
            [r[2] for r in episodes],
            "training_reward.png",
            "DQN v3 - Training Reward",
            "Training timesteps",
            "Episode reward",
        )

        if model.loss_history:
            plot_series(
                [r[0] for r in model.loss_history],
                [r[2] for r in model.loss_history],
                "training_loss.png",
                "DQN v3 - Training Loss",
                "Training timesteps",
                "DQN loss",
            )

        plot_series(
            [r["timesteps"] for r in callback.history],
            [r["mean_reward"] for r in callback.history],
            "validation_reward.png",
            "DQN v3 - Fixed-seed Validation",
            "Training timesteps",
            "Mean episode reward",
        )

        manifest = {
            "model": "DQN v3 (seed-safe)",
            "scenario_config": CONFIG,
            "git_commit": git_head(),
            "algorithm_seed": args.seed,
            "train_seed_rule":
                f"{TRAIN_SEED_BASE} + episode_index_zero_based",
            "train_seeds_completed": completed_seeds,
            "validation_seeds": list(VALIDATION_SEEDS),
            "benchmark_seeds_reserved": list(BENCHMARK_SEEDS),
            "timesteps": args.timesteps,
            "best_step": callback.best_step,
            "best_validation_mean_reward": callback.best_score,
            "best_checkpoint": str(
                BEST_MODEL.relative_to(ROOT)
            ),
            "best_checkpoint_sha256": sha256(BEST_MODEL),
            "last_checkpoint_sha256": sha256(LAST_MODEL),
            "network_slicing_env_sha256": sha256(
                TV3_DIR / "network_slicing_env.py"
            ),
            "train_dqn_sha256": sha256(
                TV3_DIR / "train_dqn.py"
            ),
            "validation_history": callback.history,
            "hyperparameters": {
                "learning_rate": 0.001,
                "buffer_size": 20000,
                "learning_starts": 1000,
                "batch_size": 64,
                "gamma": 0.99,
                "target_update_interval": 200,
                "exploration_fraction": 0.3,
                "eval_freq": EVAL_FREQ,
            },
        }

        (
            RESULT_DIR / "training_manifest.json"
        ).write_text(
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        print("\nPASS: DQN v3 training and validation complete")
        print(f"Best checkpoint: {BEST_MODEL}")
        print(f"Best step: {callback.best_step}")
        print(
            f"SHA-256: {manifest['best_checkpoint_sha256']}"
        )

    finally:
        callback.close()
        train_env.close()


if __name__ == "__main__":
    main()
