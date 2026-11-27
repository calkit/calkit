"""Plot the measurements with the fitted decay."""

import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Fixed ids in the SVG, so the same plot is the same file
plt.rcParams["svg.hashsalt"] = "fit"
t, y = np.loadtxt("data/decay.csv", delimiter=",", skiprows=1).T
with open("results/fit.json") as f:
    fit = json.load(f)
fig, ax = plt.subplots(figsize=(5, 3))
ax.plot(t, y, "o", label="Measured")
ax.plot(t, fit["amplitude"] * np.exp(-fit["rate"] * t), "--", label="Fit")
ax.set_xlabel("t")
ax.set_ylabel("y")
ax.legend()
fig.tight_layout()
os.makedirs("figures", exist_ok=True)
fig.savefig("figures/fit.svg", metadata={"Date": None})
