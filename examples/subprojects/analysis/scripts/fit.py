"""Fit a quadratic to the experiment's measurements and plot it."""

import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

x, y = np.loadtxt(
    "../experiment/data/measurements.csv", delimiter=",", skiprows=1
).T
coeffs = np.polyfit(x, y, deg=2)
os.makedirs("results", exist_ok=True)
with open("results/fit.json", "w") as f:
    json.dump({"coefficients": [round(c, 4) for c in coeffs]}, f, indent=2)
os.makedirs("figures", exist_ok=True)
fig, ax = plt.subplots(figsize=(5, 3.5), layout="constrained")
ax.plot(x, y, "o", label="Measured")
ax.plot(x, np.polyval(coeffs, x), label="Quadratic fit")
ax.set_xlabel("$x$")
ax.set_ylabel("$y$")
ax.legend()
fig.savefig("figures/fit.png", dpi=150)
