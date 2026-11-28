"""Work out the oscillator's energy over time from the simulation."""

import json
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Fixed ids in the SVG, so the same plot is the same file
plt.rcParams["svg.hashsalt"] = "energy"
t, x, v = np.loadtxt("data/sim.csv", delimiter=",", skiprows=1).T
with open("results/sim.json") as f:
    sim = json.load(f)
omega = sim["omega"]
energy = 0.5 * (v**2 + omega**2 * x**2)
# One cycle of the undamped oscillator
n_cycle = round(2 * np.pi / omega / sim["dt"])
loss = 1 - np.mean(energy[n_cycle:] / energy[:-n_cycle])
os.makedirs("results", exist_ok=True)
with open("results/energy.json", "w") as f:
    json.dump({"loss_per_cycle": float(loss)}, f, indent=2)
fig, ax = plt.subplots(figsize=(5, 3))
ax.semilogy(t, energy / energy[0])
ax.set_xlabel("t")
ax.set_ylabel("Energy / initial energy")
fig.tight_layout()
os.makedirs("figures", exist_ok=True)
fig.savefig("figures/energy.svg", metadata={"Date": None})
