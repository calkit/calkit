"""Fit the decay rate with a straight line through the log of the data."""

import json
import os

import numpy as np

t, y = np.loadtxt("data/decay.csv", delimiter=",", skiprows=1).T
slope, intercept = np.polyfit(t, np.log(y), 1)
rate = -slope
os.makedirs("results", exist_ok=True)
with open("results/fit.json", "w") as f:
    json.dump(
        {
            "rate": rate,
            "amplitude": float(np.exp(intercept)),
            "half_life": float(np.log(2) / rate),
            "n_points": int(t.size),
        },
        f,
        indent=2,
    )
