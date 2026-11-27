"""Generate noisy measurements of a quantity decaying exponentially."""

import os

import numpy as np

rng = np.random.default_rng(42)
t = np.linspace(0, 10, 41)
y = 2.5 * np.exp(-0.35 * t) * (1 + 0.04 * rng.standard_normal(t.size))
os.makedirs("data", exist_ok=True)
np.savetxt(
    "data/decay.csv",
    np.column_stack([t, y]),
    delimiter=",",
    header="t,y",
    comments="",
    fmt="%.4f",
)
