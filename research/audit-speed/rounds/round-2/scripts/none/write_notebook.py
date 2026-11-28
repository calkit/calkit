"""Write the no-framework arm's figures.ipynb, unexecuted.

Stands in for the researcher writing the notebook's cells by hand. The
plotting code matches shared/make_figure.py.
"""

import sys

import nbformat

CELLS = [
    ("markdown", "# Figures\n\nFigure 1 for the report: mean score by week."),
    (
        "code",
        """import matplotlib.pyplot as plt
import pandas as pd

WEEKS = [0, 4, 8, 12]
ARMS = {"training": ("Training", "#257de0"), "control": ("Control", "#f47230")}
DODGE = {"training": 0.15, "control": -0.15}""",
    ),
    ("code", 'df = pd.read_csv("data/merged_final.csv")\ndf.shape'),
    (
        "code",
        """fig, ax = plt.subplots(figsize=(5.5, 3.6))
for arm, (label, color) in ARMS.items():
    sub = df[df["arm"] == arm][[f"score_w{w}" for w in WEEKS]]
    mean = sub.mean()
    half = 1.96 * sub.sem()
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
fig.savefig("figures/score_by_week.png", dpi=150, metadata={"Software": None})""",
    ),
]


def main() -> None:
    nb = nbformat.v4.new_notebook()
    nb.metadata["kernelspec"] = {
        "name": "python3",
        "display_name": "Python 3 (ipykernel)",
        "language": "python",
    }
    for i, (kind, src) in enumerate(CELLS):
        cell = (
            nbformat.v4.new_markdown_cell(src)
            if kind == "markdown"
            else nbformat.v4.new_code_cell(src)
        )
        cell["id"] = f"cell-{i}"
        nb.cells.append(cell)
    nbformat.write(nb, sys.argv[1])


if __name__ == "__main__":
    main()
