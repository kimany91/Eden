"""Loudness and peak measurements (ITU-R BS.1770-4 / EBU R128).

* K-weighting: high shelf (+4 dB above ~1.7 kHz) then high-pass (~38 Hz),
  designed for any sample rate.
* Integrated loudness: 400 ms blocks, 75 % overlap, absolute gate −70 LUFS,
  relative gate −10 LU.
* Short-term loudness (3 s) and loudness range (EBU Tech 3342: gates −70
  LUFS absolute and −20 LU relative, 10th to 95th percentile).
* True peak: the peak of the continuous waveform, by ideal band-limited
  interpolation at 8× refined between its points (``oversampling``: within
  0.01 dB, no interpolation-filter roll-off on bright transients); the
  reading of libebur128 (4×, 49-tap filter) is taken too, and the higher
  one is kept. FFmpeg's meters resample to 192 kHz first and can read up to
  about 0.3 dB higher than both.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import sosfilt

from eden.mix.oversampling import meter_peak, true_peak

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
    power = weighted[:, 0] ** 2
    for c in range(1, weighted.shape[1]):  # channel weights are 1 for L/R/C
        power += weighted[:, c] ** 2
    cumulative = np.empty(power.size + 1)
    cumulative[0] = 0.0
    np.cumsum(power, out=cumulative[1:])
    starts = np.arange(0, weighted.shape[0] - size + 1, step)
    total = (cumulative[starts + size] - cumulative[starts]) / size
    with np.errstate(divide="ignore"):
        return -0.691 + 10 * np.log10(np.maximum(total, 0.0))


def integrated_loudness(x: np.ndarray, fs: float) -> float:
    """Integrated loudness in LUFS (−inf if the signal is silent)."""
    return gated_loudness(block_loudness(x, fs))


def gated_loudness(blocks: np.ndarray) -> float:
    """Integrated loudness from the 400 ms block loudness values (both gates applied)."""
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


def short_term_loudness(x: np.ndarray, fs: float) -> np.ndarray:
    """Loudness of 3 s windows every 100 ms (LUFS)."""
    return block_loudness(x, fs, block_s=3.0, overlap=1 - 0.1 / 3.0)


FELT_PERCENTILE = 95.0


def felt_loudness(x: np.ndarray, fs: float) -> float:
    """How loud the song FEELS: the loudness its loud sections hold (95th percentile of the 3 s
    short-term loudness, over the windows above the absolute gate). A song with quiet verses and a
    full hook feels as loud as its hook; its average (integrated) sits far lower, and a master
    aimed on the average over-gains it — the hook saturates and the verses swell (heard by a
    user). −inf when the signal is silent."""
    st = short_term_loudness(x, fs)
    st = st[st > ABS_GATE]
    return float(np.percentile(st, FELT_PERCENTILE)) if st.size else -math.inf


def loudness_range(x: np.ndarray, fs: float) -> float:
    """EBU Tech 3342 loudness range in LU (0 for signals shorter than a few seconds)."""
    st = short_term_loudness(x, fs)
    st = st[st > ABS_GATE]
    if st.size < 2:
        return 0.0
    power = 10 ** ((st + 0.691) / 10)
    relative = -0.691 + 10 * math.log10(power.mean()) - 20.0
    kept = st[st > relative]
    if kept.size < 2:
        return 0.0
    return float(np.percentile(kept, 95) - np.percentile(kept, 10))


def true_peak_db(x: np.ndarray, fs: float) -> float:
    """True peak in dBTP: the higher of the continuous waveform's peak and libebur128's reading
    (4×, whose short filter can read a little above it)."""
    x = np.asarray(x, dtype=np.float64)
    peak = max(true_peak(x), meter_peak(x, fs))
    return 20 * math.log10(peak) if peak > 0 else -math.inf


def sample_peak_db(x: np.ndarray) -> float:
    peak = float(np.max(np.abs(x))) if np.size(x) else 0.0
    return 20 * math.log10(peak) if peak > 0 else -math.inf
