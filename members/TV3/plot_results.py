
"""
TV3 - Ve bieu do KPI cua DQN v2.

Nguon du lieu:
    members/TV3/results/dqn_runs.csv
    members/TV3/results/dqn_aggregate.csv

Output:
    members/TV3/figures/

Khong tinh lai KPI cua TV1.
Khong thay doi du lieu CSV goc.
"""

from pathlib import Path
import csv
import matplotlib.pyplot as plt
import numpy as np


# ============================================================
# 1. THU MUC VA DU LIEU CHUNG
# ============================================================

TV3_DIR = Path(__file__).resolve().parent

RESULTS_DIR = TV3_DIR / "results"
FIGURES_DIR = TV3_DIR / "figures"

RUNS_CSV = RESULTS_DIR / "dqn_runs.csv"
AGGREGATE_CSV = RESULTS_DIR / "dqn_aggregate.csv"

SCENARIOS = [
    "stable_load",
    "urllc_burst",
    "poor_channel",
]

LABELS = [
    "Stable Load",
    "URLLC Burst",
    "Poor Channel",
]

FIGURES_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# 2. DOC CSV
# ============================================================

def read_csv(path):
    if not path.is_file():
        raise FileNotFoundError(
            f"Khong tim thay file CSV: {path}"
        )

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:
        rows = list(csv.DictReader(file))

    if not rows:
        raise ValueError(f"CSV khong co du lieu: {path}")

    return rows


runs = read_csv(RUNS_CSV)
aggregates = read_csv(AGGREGATE_CSV)

aggregate_map = {
    row["scenario_id"]: row
    for row in aggregates
    if row["scheduler"] == "dqn"
}

for scenario in SCENARIOS:
    if scenario not in aggregate_map:
        raise ValueError(
            f"Thieu scenario trong CSV: {scenario}"
        )


# ============================================================
# 3. HAM VE BIEU DO
# ============================================================

def plot_metric(
    metric,
    title,
    ylabel,
    filename,
    percentage=False
):
    means = []
    stds = []

    for scenario in SCENARIOS:
        row = aggregate_map[scenario]

        mean = float(row[f"{metric}_mean"])
        std = float(row[f"{metric}_std"])

        if percentage:
            mean *= 100
            std *= 100

        means.append(mean)
        stds.append(std)

    x = np.arange(len(SCENARIOS))

    fig, ax = plt.subplots(figsize=(9, 5.5))

    bars = ax.bar(
        x,
        means,
        yerr=stds,
        capsize=6,
        width=0.58,
        color="#2878B5",
        edgecolor="#174C72",
        alpha=0.9,
    )

    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=11)

    ax.set_xticks(x)
    ax.set_xticklabels(LABELS)

    ax.grid(
        axis="y",
        linestyle="--",
        alpha=0.3
    )

    ax.set_axisbelow(True)

    upper = max(
        (m + s for m, s in zip(means, stds)),
        default=1.0
    )

    ax.set_ylim(0, max(upper * 1.25, 0.01))

    for bar, value, std in zip(bars, means, stds):
        ax.annotate(
            f"{value:.2f}",
            xy=(
                bar.get_x() + bar.get_width() / 2,
                value + std
           ),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=10,
            fontweight="bold"
        )

    fig.text(
        0.5,
        0.01,
        "DQN v2 | 3 evaluation seeds: 42, 43, 44 | "
        "500 slots/run | Error bars: sample std",
        ha="center",
        fontsize=9
    )

    fig.tight_layout(rect=(0, 0.04, 1, 1))

    output_path = FIGURES_DIR / filename

    fig.savefig(
        output_path,
        dpi=300,
        bbox_inches="tight"
    )

    plt.close(fig)

    print(f"Created: {output_path}")


# ============================================================
# 4. VE THROUGHPUT eMBB
# ============================================================

plot_metric(
    metric="served_embb_mbps",
    title="DQN v2 - eMBB Throughput",
    ylabel="Throughput (Mbps)",
    filename="embb_throughput.png"
)


# ============================================================
# 5. VE THROUGHPUT URLLC
# ============================================================

plot_metric(
    metric="served_urllc_mbps",
    title="DQN v2 - URLLC Throughput",
    ylabel="Throughput (Mbps)",
    filename="urllc_throughput.png"
)


# ============================================================
# 6. VE URLLC COMPLETION RATE
# ============================================================

plot_metric(
    metric="urllc_completion_rate",
    title="DQN v2 - URLLC Completion Rate",
    ylabel="Completion Rate (%)",
    filename="urllc_completion.png",
    percentage=True
)


# ============================================================
# 7. VE URLLC DROP RATE
# ============================================================

plot_metric(
    metric="urllc_drop_rate",
    title="DQN v2 - URLLC Packet Drop Rate",
    ylabel="Packet Drop Rate (%)",
    filename="urllc_drop.png",
    percentage=True
)


# ============================================================
# 8. VE URLLC MEAN DELAY
# ============================================================

plot_metric(
    metric="urllc_mean_delay_ms",
    title="DQN v2 - URLLC Mean Delay",
    ylabel="Mean Delay (ms)",
    filename="urllc_mean_delay.png"
)


# ============================================================
# 9. VE URLLC P95 DELAY
# ============================================================

plot_metric(
    metric="urllc_p95_delay_ms",
    title="DQN v2 - URLLC P95 Delay",
    ylabel="P95 Delay (ms)",
    filename="urllc_p95_delay.png"
)


# ============================================================
# 10. VE RB ALLOCATION
# ============================================================

embb_rb = [
    float(aggregate_map[s]["mean_embb_rb_mean"])
    for s in SCENARIOS
]

urllc_rb = [
    float(aggregate_map[s]["mean_urllc_rb_mean"])
    for s in SCENARIOS
]

x = np.arange(len(SCENARIOS))

fig, ax = plt.subplots(figsize=(9, 5.5))

ax.bar(
    x,
    embb_rb,
    label="eMBB",
    color="#2878B5"
)

ax.bar(
    x,
    urllc_rb,
    bottom=embb_rb,
    label="URLLC",
    color="#E69F00"
)

ax.set_title(
    "DQN v2 - Mean RB Allocation",
    fontsize=14,
    fontweight="bold"
)

ax.set_ylabel("Allocated Resource Blocks")

ax.set_xticks(x)
ax.set_xticklabels(LABELS)

ax.set_ylim(0, 55)
ax.legend()

ax.grid(axis="y", linestyle="--", alpha=0.3)
ax.set_axisbelow(True)

fig.text(
    0.5,
    0.01,
    "Total RB = 50 | Average of 3 seeds per scenario",
    ha="center",
    fontsize=9
)

fig.tight_layout(rect=(0, 0.04, 1, 1))

output_path = FIGURES_DIR / "rb_allocation.png"
fig.savefig(output_path, dpi=300, bbox_inches="tight")
plt.close(fig)

print(f"Created: {output_path}")


print("\n==============================================")
print("TV3 - KPI FIGURES COMPLETED")
print("==============================================")
print("Total figures: 7")
print(f"Output directory: {FIGURES_DIR}")
