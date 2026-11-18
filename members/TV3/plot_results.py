
"""Plot seven DQN v3 KPI figures from benchmark_v3/dqn_aggregate.csv.

Run from NSL root:
  python members/TV3/plot_results.py
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

TV3_DIR = Path(__file__).resolve().parent

SCENARIOS = (
    "stable_load",
    "urllc_burst",
    "poor_channel",
)

LABELS = (
    "Stable Load",
    "URLLC Burst",
    "Poor Channel",
)


def read_aggregate(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:
        rows = list(csv.DictReader(f))

    data = {
        r["scenario_id"]: r
        for r in rows
        if r["scheduler"] == "dqn"
    }

    if set(SCENARIOS) - set(data):
        raise RuntimeError(
            "DQN v3 aggregate is missing a scenario"
        )

    return data


def plot_metric(
    data: dict,
    metric: str,
    title: str,
    ylabel: str,
    output: Path,
    percent: bool = False,
) -> None:
    scale = 100.0 if percent else 1.0

    means = [
        float(data[s][f"{metric}_mean"]) * scale
        for s in SCENARIOS
    ]

    stds = [
        float(data[s][f"{metric}_std"]) * scale
        for s in SCENARIOS
    ]

    x = np.arange(len(SCENARIOS))

    fig, ax = plt.subplots(figsize=(9, 5.5))

    bars = ax.bar(
        x,
        means,
        yerr=stds,
        capsize=5,
        width=0.58,
    )

    ax.set_title(f"DQN v3 - {title}")
    ax.set_ylabel(ylabel)
    ax.set_xticks(x, LABELS)

    ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)

    top = max(
        (m + e for m, e in zip(means, stds)),
        default=1,
    )
    ax.set_ylim(0, max(0.01, top * 1.25))

    for bar, value in zip(bars, means):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"{value:.2f}",
            ha="center",
            va="bottom",
        )

    fig.text(
        0.5,
        0.015,
        "Mean +/- sample std across seeds 42, 43, 44",
        ha="center",
        fontsize=9,
    )

    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(output, dpi=250, bbox_inches="tight")
    plt.close(fig)

    print(f"Created: {output}")


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--input",
        type=Path,
        default=(
            TV3_DIR / "results" /
            "benchmark_v3" / "dqn_aggregate.csv"
        ),
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=(
            TV3_DIR / "figures" / "benchmark_v3"
        ),
    )

    args = parser.parse_args()

    args.output.mkdir(
        parents=True,
        exist_ok=True,
    )

    data = read_aggregate(args.input)

    metrics = (
        (
            "served_embb_mbps",
            "eMBB Throughput",
            "Mbps",
            "embb_throughput.png",
            False,
        ),
        (
            "served_urllc_mbps",
            "URLLC Throughput",
            "Mbps",
            "urllc_throughput.png",
            False,
        ),
        (
            "urllc_completion_rate",
            "URLLC Completion",
            "%",
            "urllc_completion.png",
            True,
        ),
        (
            "urllc_drop_rate",
            "URLLC Drop",
            "%",
            "urllc_drop.png",
            True,
        ),
        (
            "urllc_mean_delay_ms",
            "URLLC Mean Delay",
            "ms",
            "urllc_mean_delay.png",
            False,
        ),
        (
            "urllc_p95_delay_ms",
            "URLLC P95 Delay",
            "ms",
            "urllc_p95_delay.png",
            False,
        ),
    )

    for metric, title, ylabel, filename, percent in metrics:
        plot_metric(
            data,
            metric,
            title,
            ylabel,
            args.output / filename,
            percent,
        )

    # Seventh chart: stacked RB allocation.
    x = np.arange(len(SCENARIOS))

    embb = [
        float(data[s]["mean_embb_rb_mean"])
        for s in SCENARIOS
    ]

    urllc = [
        float(data[s]["mean_urllc_rb_mean"])
        for s in SCENARIOS
    ]

    fig, ax = plt.subplots(figsize=(9, 5.5))

    ax.bar(x, embb, label="eMBB")
    ax.bar(
        x,
        urllc,
        bottom=embb,
        label="URLLC",
    )

    ax.set_title("DQN v3 - Mean RB Allocation")
    ax.set_ylabel("Allocated RB")
    ax.set_xticks(x, LABELS)
    ax.set_ylim(0, 55)

    ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)
    ax.legend()

    fig.tight_layout()

    file = args.output / "rb_allocation.png"

    fig.savefig(
        file,
        dpi=250,
        bbox_inches="tight",
    )
    plt.close(fig)

    print(f"Created: {file}")
    print(
        "PASS: seven DQN v3 charts saved, "
        "v2 figures unchanged"
    )


if __name__ == "__main__":
    main()
