"""Harmonic saturation and soft clipping, oversampled to keep aliasing low.

The saturation runs at 4× the sample rate and the soft clipper, driven
harder, at 8× (``oversampling.shape_change``): the harmonics they create
above the audible band are filtered out before coming back down. Only the change the waveshaper makes goes
through the filters, so a signal it does not touch comes out bit-exact.
``drive`` and ``mix`` set how much colour is added; at mix 0 the signal is
returned unchanged.
"""

from __future__ import annotations

import numpy as np

from eden.mix.oversampling import shape_change

OVERSAMPLE = 4
CLIP_OVERSAMPLE = 8


def _shape(x: np.ndarray, drive: float, asymmetry: float) -> np.ndarray:
    """tanh curve with optional even harmonics (asymmetry), unity gain at low level."""
    g = max(drive, 1e-6)
    y = np.tanh(g * (x + asymmetry)) - np.tanh(g * asymmetry)
    return y / g


def saturate(x: np.ndarray, fs: float, drive: float, mix: float = 1.0, asymmetry: float = 0.0
             ) -> np.ndarray:
    if mix <= 0 or drive <= 0:
        return x
    return x + mix * shape_change(x, fs, OVERSAMPLE, lambda u: _shape(u, drive, asymmetry))


def clip_curve(u: np.ndarray, ceiling: float) -> np.ndarray:
    """The soft clipper's curve: linear up to 70 % of ``ceiling``, then a tanh knee to it."""
    knee = 0.7 * ceiling
    out = u.copy()
    over = np.abs(u) > knee
    excess = (np.abs(u[over]) - knee) / (ceiling - knee)
    out[over] = np.sign(u[over]) * (knee + (ceiling - knee) * np.tanh(excess))
    return out


def soft_clip(x: np.ndarray, fs: float, ceiling: float) -> np.ndarray:
    """Round off peaks above 70 % of ``ceiling`` (linear) with a smooth curve, oversampled."""
    return x + shape_change(x, fs, CLIP_OVERSAMPLE, lambda u: clip_curve(u, ceiling))
