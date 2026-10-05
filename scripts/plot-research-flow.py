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
fig, ((ax1, ax2), (ax3, ax4), (ax5, ax6)) = plt.subplots(
    3, 2, figsize=(12, 13.5)
)
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
for name, style, color, label in [
    ("combined", "-", COLORS["lean"], "lean automated vs. stage-gate manual"),
    ("automated", "-", MUTED, "both automated"),
    ("manual", "--", MUTED, "both manual"),
]:
    ax2.plot(
        pct,
        ws["student_days_ratio"][name],
        style,
        color=color,
        lw=2,
        marker="o",
        ms=6,
        label=label,
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
ax3.set_ylim(top=ax3.get_ylim()[1] * 1.12)
ax3.legend(frameon=False, fontsize=9, loc="upper center", ncol=2)
# Lean with automation against stage-gate without, as the latter's
# handoffs get costlier and flaws more common
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
ax4.set_ylabel(
    "Stage-gate handoff and review prep cost,\nrelative to manual tooling"
)
ax4.set_title("Stage-gate manual ÷ lean automated time", loc="left")
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
# Adopting the tooling, on a first paper and on later ones
labels = {
    "diy/word": "DIY, PI on Word",
    "diy/adopts": "DIY, PI adopts",
    "calkit/word": "Calkit, PI on Word",
    "calkit/browser": "Calkit, PI adopts (browser)",
}
y = np.arange(len(labels))[::-1]
for k, (paper, color) in enumerate(
    [("first", COLORS["lean"]), ("later", "#1baf7a")]
):
    vals = [r["adoption"][name][paper]["days_ratio"] for name in labels]
    pos = y + (0.5 - k) * 0.38
    ax5.barh(pos, vals, 0.36, color=color, label=f"{paper} paper", zorder=2)
    for p_, v in zip(pos, vals):
        ax5.text(
            v - 0.04, p_, f"{v:.2f}×", ha="right", va="center", color="white"
        )
for level in (1, 2):
    ax5.axvline(level, color=MUTED, lw=1, ls="--" if level == 2 else "-")
ax5.set_yticks(y, list(labels.values()))
ax5.set_xlabel("Stage-gate manual time ÷ lean automated time")
ax5.set_title("Learning the tooling, and the PI's side of it", loc="left")
ax5.grid(axis="x", color=GRID, zorder=0)
ax5.set_xlim(0, 2.6)
ax5.legend(frameon=False, loc="upper right")
# How much learning a first paper can absorb
ls_ = r["learn_sweep"]
for name, style, label in [
    ("none", "-", "PI needs no translation"),
    ("word", "--", "PI on Word, merged by hand"),
]:
    ax6.plot(
        ls_["learn_days"],
        ls_["days_ratio"][name],
        style,
        color=COLORS["lean"],
        lw=2,
        marker="o",
        ms=6,
        label=label,
    )
for level in (1, 2):
    ax6.axhline(level, color=MUTED, lw=1, ls="--" if level == 2 else "-")
for days, label in [(3, "Calkit"), (30, "DIY")]:
    ax6.axvline(days, color=INK, lw=1, ls=":")
    ax6.text(days + 2, 1.1, label, color=INK, fontsize=9)
ax6.set_xlabel("Student days learning and setting up the tooling")
ax6.set_ylabel("Stage-gate manual time ÷ lean automated time")
ax6.set_title("First paper, by learning cost", loc="left")
ax6.grid(color=GRID)
ax6.legend(frameon=False, loc="upper right")
fig.tight_layout()
fig.savefig("docs/img/research-flow.png", dpi=150)
# What Calkit would need to deliver, one goal at a time, on a first paper
goals = r["goals"]
alternatives = {
    "diy tooling": "DIY in place of Calkit's tooling",
    "all goals, no agents": "every goal, without agents",
}
rows = [(g["step"], g) for g in goals["steps"]] + [
    (alternatives[name], g) for name, g in goals["alternatives"].items()
]
names = [
    name if k == 0 or k >= len(goals["steps"]) else f"+ {name}"
    for k, (name, _) in enumerate(rows)
]
fig, (ax, ax_flaws, ax_loops) = plt.subplots(
    1,
    3,
    figsize=(15, 6.5),
    sharey=True,
    gridspec_kw={"width_ratios": [1.6, 1, 1]},
)
# A gap between the steps and the alternatives to them
y = np.array(
    [
        len(rows) - 1 - k - (0.6 if k >= len(goals["steps"]) else 0.0)
        for k in range(len(rows))
    ]
)
for k, (key, color, label) in enumerate(
    [
        ("days_ratio", COLORS["lean"], "time to an approved paper"),
        ("student_days_ratio", "#1baf7a", "papers per PhD"),
        ("correct_ratio", "#eda100", "correct findings per year"),
    ]
):
    vals = [g[key] for _, g in rows]
    pos = y + (1 - k) * 0.27
    ax.barh(pos, vals, 0.25, color=color, label=label, zorder=2)
    for p_, v in zip(pos, vals):
        ax.text(v + 0.03, p_, f"{v:.1f}×", ha="left", va="center", fontsize=8)
ax.axvline(1, color=MUTED, lw=1)
ax.axvline(2, color=MUTED, lw=1, ls="--")
ax.set_yticks(y, names)
for tick in ax.get_yticklabels()[len(goals["steps"]) :]:
    tick.set_fontstyle("italic")
ax.set_xlim(0, 3.3)
ax.set_xlabel("Improvement over the status quo, first paper")
ax.set_title("Productivity and value", loc="left")
ax.grid(axis="x", color=GRID, zorder=0)
ax.legend(frameon=False, loc="upper right", fontsize=9)
# Quality: what gets through, and how often work is checked
for axis, key, title, label, fmt in [
    (
        ax_flaws,
        "flawed_per_finding_mean",
        "Errors reaching an approved paper",
        "Flawed findings per finding",
        "{:.3f}",
    ),
    (
        ax_loops,
        "loops_per_month_mean",
        "Feedback loops",
        "Reviews, re-checks and self-catches per month",
        "{:.1f}",
    ),
]:
    vals = [g[key] for _, g in rows]
    axis.barh(y, vals, 0.6, color=INK, zorder=2)
    axis.axvline(vals[0], color=MUTED, lw=1, ls="--")
    for p_, v in zip(y, vals):
        axis.text(
            v + max(vals) * 0.02,
            p_,
            fmt.format(v),
            ha="left",
            va="center",
            fontsize=8,
        )
    axis.set_xlim(0, max(vals) * 1.25)
    axis.set_xlabel(label)
    axis.set_title(title, loc="left")
    axis.grid(axis="x", color=GRID, zorder=0)
    axis.tick_params(axis="y", length=0)
fig.suptitle(
    "Lean research with Calkit and agents, goal by goal",
    x=0.01,
    ha="left",
    fontsize=12,
)
fig.tight_layout()
fig.savefig("docs/img/research-flow-goals.png", dpi=150)
