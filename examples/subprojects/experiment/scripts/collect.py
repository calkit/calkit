"""Simulate measurements with a calibrated sensor."""

import json
import os

import numpy as np

with open("calibration/results/calibration.json") as f:
    gain = json.load(f)["gain"]
rng = np.random.default_rng(seed=1)
x = np.linspace(0, 10, 51)
y = gain * (0.5 * x**2 + rng.normal(scale=2.0, size=x.size))
os.makedirs("data", exist_ok=True)
np.savetxt(
    "data/measurements.csv",
    np.column_stack([x, y]),
    delimiter=",",
    header="x,y",
    comments="",
    fmt="%.6f",
)
