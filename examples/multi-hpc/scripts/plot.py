"""Plot the simulation's results."""

import os

import matplotlib.pyplot as plt
import pandas as pd

df = pd.read_csv("data/simulation/results.csv")
with open("data/simulation/host.txt") as f:
    host = f.read().strip()
fig, ax = plt.subplots()
ax.plot(df["t"], df["u"])
ax.set_xlabel("t")
ax.set_ylabel("u")
ax.set_title(f"Simulated on {host}")
os.makedirs("figures", exist_ok=True)
fig.savefig("figures/simulation.png")
