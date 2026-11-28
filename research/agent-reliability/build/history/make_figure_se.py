"""Plot mean cognitive score by assessment week and arm."""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

WEEKS = [0, 4, 8, 12]
ARMS = {"training": ("Training", "#257de0"), "control": ("Control", "#f47230")}
DODGE = {"training": 0.15, "control": -0.15}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(args.data)
    fig, ax = plt.subplots(figsize=(5.5, 3.6))
    for arm, (label, color) in ARMS.items():
        sub = df[df["arm"] == arm][[f"score_w{w}" for w in WEEKS]]
        mean = sub.mean()
        half = sub.sem()
        x = [w + DODGE[arm] for w in WEEKS]
        ax.errorbar(
            x,
            mean.values,
            yerr=half.values,
            color=color,
            linewidth=2,
            marker="o",
            markersize=6,
            capsize=3,
            label=label,
        )
        ax.annotate(
            label,
            (x[-1], mean.values[-1]),
            xytext=(8, 0),
            textcoords="offset points",
            va="center",
            color="#333333",
        )
    ax.set_xticks(WEEKS)
    ax.set_xlim(-1, 14.5)
    ax.set_xlabel("Week")
    ax.set_ylabel("Mean cognitive score")
    ax.grid(axis="y", color="#e7e7e7", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#c2c2c2")
    ax.legend(frameon=False, loc="upper left")
    fig.tight_layout()
    fig.savefig(args.out, dpi=150, metadata={"Software": None})


if __name__ == "__main__":
    main()
