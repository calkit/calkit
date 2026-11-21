"""Fit the sensor's gain against known reference values."""

import json
import os

import numpy as np

rng = np.random.default_rng(seed=0)
reference = np.linspace(1, 5, 9)
reading = 1.08 * reference + rng.normal(scale=0.02, size=reference.size)
gain = float(np.linalg.lstsq(reading[:, None], reference, rcond=None)[0][0])
os.makedirs("results", exist_ok=True)
with open("results/calibration.json", "w") as f:
    json.dump({"gain": round(gain, 4)}, f, indent=2)
