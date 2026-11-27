"""Plot mean outcome by SES category and condition."""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

SES_ORDER = ["low", "middle", "high", "missing"]
COLORS = {"control": "#7a8794", "treatment": "#2f6db5"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(args.clean)
    levels = [s for s in SES_ORDER if s in set(df["ses"])]
    stats = (
        df.groupby(["ses", "condition"])["outcome"]
        .agg(["mean", "sem", "count"])
        .reset_index()
    )
    fig, ax = plt.subplots(figsize=(5.5, 3.6))
    width = 0.36
    x = np.arange(len(levels))
    for i, condition in enumerate(["control", "treatment"]):
        sub = stats[stats["condition"] == condition].set_index("ses")
        sub = sub.reindex(levels)
        ax.bar(
            x + (i - 0.5) * width,
            sub["mean"],
            width,
            yerr=1.96 * sub["sem"],
            capsize=3,
            color=COLORS[condition],
            label=condition.capitalize(),
        )
    ax.set_xticks(x)
    ax.set_xticklabels([s.capitalize() for s in levels])
    ax.set_xlabel("SES category")
    ax.set_ylabel("Mean outcome score")
    ax.set_ylim(40, 70)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper left")
    fig.tight_layout()
    fig.savefig(args.out, dpi=150, metadata={"Software": None})


if __name__ == "__main__":
    main()
