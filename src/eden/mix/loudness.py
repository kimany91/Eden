"""Loudness and peak measurements (ITU-R BS.1770-4 / EBU R128).

* K-weighting: high shelf (+4 dB above ~1.7 kHz) then high-pass (~38 Hz),
  designed for any sample rate.
* Integrated loudness: 400 ms blocks, 75 % overlap, absolute gate −70 LUFS,
  relative gate −10 LU.
* True peak: 4× oversampling.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import resample_poly, sosfilt

ABS_GATE = -70.0
REL_GATE = -10.0


def k_weighting(fs: float) -> np.ndarray:
    """Second-order sections of the BS.1770 K-weighting filter for sample rate ``fs``.

    Exact re-derivation of the standard's two stages (as in libebur128): at
    48 kHz it gives the coefficients printed in the recommendation.
    """
    f0, gain, q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    k = math.tan(math.pi * f0 / fs)
    vh = 10 ** (gain / 20)
    vb = vh ** 0.4996667741545416
    a0 = 1 + k / q + k * k
    shelf = [(vh + vb * k / q + k * k) / a0, 2 * (k * k - vh) / a0, (vh - vb * k / q + k * k) / a0,
             1.0, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0]
    f0, q = 38.13547087602444, 0.5003270373238773
    k = math.tan(math.pi * f0 / fs)
    a0 = 1 + k / q + k * k
    high_pass = [1.0, -2.0, 1.0, 1.0, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0]
    return np.array([shelf, high_pass])


def _as_2d(x: np.ndarray) -> np.ndarray:
    return x[:, None] if x.ndim == 1 else x


def block_loudness(x: np.ndarray, fs: float, block_s: float = 0.4, overlap: float = 0.75
                   ) -> np.ndarray:
    """Loudness (LUFS) of successive blocks; −inf for digital silence."""
    x = _as_2d(np.asarray(x, dtype=np.float64))
    weighted = sosfilt(k_weighting(fs), x, axis=0)
    size = int(round(block_s * fs))
    step = max(1, int(round(size * (1 - overlap))))
    if weighted.shape[0] < size:
        return np.array([])
    power = weighted ** 2
    cumulative = np.vstack([np.zeros((1, power.shape[1])), np.cumsum(power, axis=0)])
    starts = np.arange(0, weighted.shape[0] - size + 1, step)
    mean_square = (cumulative[starts + size] - cumulative[starts]) / size  # per channel
    total = mean_square.sum(axis=1)  # channel weights are 1 for L/R/C
    with np.errstate(divide="ignore"):
        return -0.691 + 10 * np.log10(total)


def integrated_loudness(x: np.ndarray, fs: float) -> float:
    """Integrated loudness in LUFS (−inf if the signal is silent)."""
    blocks = block_loudness(x, fs)
    gated = blocks[blocks > ABS_GATE]
    if gated.size == 0:
        return -math.inf
    power = 10 ** ((gated + 0.691) / 10)
    relative = -0.691 + 10 * math.log10(power.mean()) + REL_GATE
    final = power[gated > relative]
    return -0.691 + 10 * math.log10(final.mean())


def loudness_of_blocks(x: np.ndarray, fs: float, mask: np.ndarray) -> float:
    """Energy-average loudness of the 400 ms blocks selected by ``mask``."""
    blocks = block_loudness(x, fs)
    n = min(blocks.size, mask.size)
    chosen = blocks[:n][mask[:n] & np.isfinite(blocks[:n])]
    if chosen.size == 0:
        return -math.inf
    return 10 * math.log10(np.mean(10 ** (chosen / 10)))


def true_peak_db(x: np.ndarray, oversample: int = 4) -> float:
    x = _as_2d(np.asarray(x, dtype=np.float64))
    if x.size == 0:
        return -math.inf
    up = resample_poly(x, oversample, 1, axis=0)
    peak = float(np.max(np.abs(up)))
    return 20 * math.log10(peak) if peak > 0 else -math.inf


def sample_peak_db(x: np.ndarray) -> float:
    peak = float(np.max(np.abs(x))) if np.size(x) else 0.0
    return 20 * math.log10(peak) if peak > 0 else -math.inf
