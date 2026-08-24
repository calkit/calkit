"""A tiny library of wave calculations, used by this project's README."""

from __future__ import annotations

import numpy as np

__all__ = ["damped_wave", "rms"]


def damped_wave(
    t: np.ndarray, damping: float = 0.3, frequency: float = 2.0
) -> np.ndarray:
    """Evaluate a damped cosine wave at times ``t``."""
    return np.exp(-damping * t) * np.cos(frequency * t)


def rms(x: np.ndarray) -> float:
    """Return the root mean square of ``x``."""
    return float(np.sqrt(np.mean(np.square(x))))
