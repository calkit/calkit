"""Plot the stage-gate versus lean research flow simulation."""

import json

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm

r = json.loads(open("results/research-flow.json").read())
COLORS = {"stage-gate": "#eb6834", "lean": "#2a78d6"}
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
STYLES = {"manual": "--", "automated": "-"}
plt.rcParams.update(
    {
        "font.size": 10,
        "text.color": INK,
        "axes.labelcolor": INK,
        "axes.edgecolor": MUTED,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)
fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(12, 9))
# Days to an approved paper for each style and tooling
x = np.arange(2)
width = 0.36
for k, pol in enumerate(["stage-gate", "lean"]):
    sc = [r["scenarios"][f"{pol}/{t}"] for t in ["manual", "automated"]]
    mean = [s["days_mean"] for s in sc]
    err = [
        [m - s["days_p10"] for m, s in zip(mean, sc)],
        [s["days_p90"] - m for m, s in zip(mean, sc)],
    ]
    pos = x + (k - 0.5) * (width + 0.02)
    ax1.bar(pos, mean, width, color=COLORS[pol], label=pol, zorder=2)
    ax1.errorbar(pos, mean, yerr=err, fmt="none", ecolor=MUTED, lw=1.2)
    for p, m in zip(pos, mean):
        ax1.text(p, 10, f"{m:.0f}", ha="center", va="bottom", color="white")
ax1.set_xticks(x, ["Manual tooling", "Automated tooling"])
ax1.set_ylabel("Working days to an approved paper")
ax1.set_title("Time to an approved paper", loc="left")
ax1.grid(axis="y", color=GRID, zorder=0)
ax1.legend(frameon=False, loc="upper right")
# Student-days per paper, as more of the wait on reviews is put to use
ws = r["wait_sweep"]
pct = [100 * f for f in ws["fractions"]]
for t, style in STYLES.items():
    ax2.plot(
        pct,
        ws["student_days_ratio"][t],
        style,
        color=INK,
        lw=2,
        marker="o",
        ms=6,
        label=f"{t} tooling",
    )
ax2.axhline(1, color=MUTED, lw=1)
ax2.set_xticks(pct)
ax2.set_xlabel("Time waiting on reviews spent on other useful work (%)")
ax2.set_ylabel("Stage-gate student-days ÷ lean student-days")
ax2.set_title("Papers per PhD, lean relative to stage-gate", loc="left")
ax2.grid(color=GRID)
ax2.legend(frameon=False)
# How often lean should hold reviews, against stage-gate's gates
sweep = r["interval_sweep"]
for t, style in STYLES.items():
    ax3.plot(
        sweep["intervals"],
        sweep["days_mean"][t],
        style,
        color=COLORS["lean"],
        lw=2,
        marker="o",
        ms=6,
        label=f"lean, {t}",
    )
    ax3.axhline(
        r["scenarios"][f"stage-gate/{t}"]["days_mean"],
        ls=style,
        color=COLORS["stage-gate"],
        lw=1.5,
        label=f"stage-gate, {t}",
    )
ax3.set_xscale("log")
ax3.set_xticks(sweep["intervals"], [str(i) for i in sweep["intervals"]])
ax3.minorticks_off()
ax3.set_xlabel("Days between lean reviews")
ax3.set_ylabel("Working days to an approved paper")
ax3.set_title("Review interval", loc="left")
ax3.grid(color=GRID)
ax3.legend(frameon=False, fontsize=9, loc="center left")
# Lean's advantage as handoffs get costlier and flaws more common
grid = np.array(r["ratio_grid"]["days_ratio"])
cmap = LinearSegmentedColormap.from_list(
    "div", [COLORS["stage-gate"], "#f0efec", COLORS["lean"]]
)
norm = TwoSlopeNorm(vcenter=1.0, vmin=min(0.5, grid.min()), vmax=grid.max())
ax4.imshow(grid, origin="lower", cmap=cmap, norm=norm, aspect="auto")
for i in range(grid.shape[0]):
    for j in range(grid.shape[1]):
        ax4.text(j, i, f"{grid[i, j]:.1f}×", ha="center", va="center")
cs = r["ratio_grid"]["cost_scales"]
fs = r["ratio_grid"]["flaw_scales"]
ax4.set_xticks(range(len(fs)), [f"{f:g}×" for f in fs])
ax4.set_yticks(range(len(cs)), [f"{c:g}×" for c in cs])
ax4.set_xlabel("Flaw rate, relative to baseline")
ax4.set_ylabel("Handoff and review prep cost,\nrelative to manual")
ax4.set_title("Stage-gate time ÷ lean time, manual tooling", loc="left")
ax4.add_patch(
    plt.Rectangle(
        (fs.index(1.0) - 0.5, cs.index(1.0) - 0.5),
        1,
        1,
        fill=False,
        ec=INK,
        lw=1.5,
    )
)
for spine in ax4.spines.values():
    spine.set_visible(False)
fig.tight_layout()
fig.savefig("docs/img/research-flow.png", dpi=150)
