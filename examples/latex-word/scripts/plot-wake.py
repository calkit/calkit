"""Plot a wake velocity deficit profile for the paper."""

import os

import matplotlib.pyplot as plt
import numpy as np

if __name__ == "__main__":
    c_t, k = 0.8, 0.05
    x_d = np.linspace(2, 10, 100)
    deficit = c_t / (8 * (1 + k * x_d) ** 2)
    fig, ax = plt.subplots(figsize=(4, 3))
    ax.plot(x_d, deficit)
    ax.set_xlabel("$x/D$")
    ax.set_ylabel(r"$\Delta U / U_\infty$")
    fig.tight_layout()
    os.makedirs("figures", exist_ok=True)
    fig.savefig("figures/wake-deficit.pdf")
