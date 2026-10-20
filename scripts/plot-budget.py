"""Plot where the 2027 workshop tour's money goes, for the one-pager."""

import json

import matplotlib.pyplot as plt

r = json.loads(open("results/2027-budget.json").read())
LABELS = {
    "fellows": "Fellows teaching\nand supporting projects",
    "development": "Development",
    "workshops": "Workshops and travel",
    "hosting": "Hosting",
}
TEAL, INK, MUTED = "#3F8F80", "#1E2A2E", "#66737A"
plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["TeX Gyre Heros", "Helvetica", "Arial"],
        "font.size": 8,
        "text.color": INK,
    }
)
cats = sorted(r["by_category"], key=r["by_category"].get)
costs = [r["by_category"][c] for c in cats]
fig, ax = plt.subplots(figsize=(3.45, 1.15))
ax.barh(range(len(cats)), costs, height=0.62, color=TEAL)
# Each bar labeled with its amount and share of the total
for i, cost in enumerate(costs):
    ax.text(
        cost + r["total"] * 0.015,
        i,
        f"${cost / 1000:,.0f}k  ({cost / r['total']:.0%})",
        va="center",
        color=INK,
    )
ax.set_yticks(range(len(cats)), [LABELS[c] for c in cats], color=INK)
ax.tick_params(axis="y", length=0)
ax.set_xticks([])
ax.set_xlim(0, max(costs) * 1.6)
for side in ["top", "right", "bottom"]:
    ax.spines[side].set_visible(False)
ax.spines["left"].set_color(MUTED)
fig.tight_layout(pad=0.2)
fig.savefig("docs/img/2027-budget.png", dpi=300)
