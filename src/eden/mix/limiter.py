"""True-peak limiter for the final master (offline, look-ahead, linked stereo).

1. Peaks are found on the reconstructed waveform (ideal 8× interpolation),
   and as a common loudness meter reads them (libebur128, whose short
   interpolation filter can read a little higher): the ceiling holds for
   both readings, not only for the samples.
2. The gain each sample needs is held from the look-ahead window before a
   peak to 20 ms after it (sliding minimum) and smoothed with the look-ahead
   window: the gain is already down when a peak arrives, without clicks,
   and does not ripple inside an 808 cycle (distortion).
3. The recovery (release) follows a smooth exponential on 1 ms frames.
4. The output is measured again; if the ceiling is still exceeded (the gain
   aims 0.02 dB under it, so this is rare), the pass is repeated on the
   remaining excess. That last measurement is the reported true peak.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import minimum_filter1d, uniform_filter1d

from eden.mix.oversampling import meter_envelope, peak_envelope

OVERSAMPLE = 8
HOLD_MS = 20.0  # a 40 Hz half-cycle is 12.5 ms: shorter, the gain would ripple inside each cycle
AIM_DB = 0.02  # the gain aims this far under the ceiling, so one pass is usually enough


@dataclass
class LimiterResult:
    audio: np.ndarray
    max_reduction_db: float
    true_peak_db: float


def _release(gain: np.ndarray, fs: float, release_ms: float) -> np.ndarray:
    """Hold reductions and let the gain recover exponentially (1 ms resolution)."""
    frame = max(1, int(fs / 1000))
    n = gain.size
    frames = -(-n // frame)
    padded = np.pad(gain, (0, frames * frame - n), constant_values=1.0)
    per_frame = padded.reshape(frames, frame).min(axis=1)
    coef = math.exp(-1 / max(release_ms, 1e-6))  # per 1 ms frame
    out = np.empty(frames)
    state = 1.0
    for i, target in enumerate(per_frame):
        state = target if target < state else coef * state + (1 - coef) * target
        out[i] = state
    centers = (np.arange(frames) + 0.5) * frame
    return np.interp(np.arange(n), centers, out)


def _peaks(x: np.ndarray, fs: float) -> np.ndarray:
    return np.maximum(peak_envelope(x, OVERSAMPLE), meter_envelope(x, fs))


def gain_for(peak: np.ndarray, fs: float, aim: float, lookahead_ms: float = 1.5,
             release_ms: float = 80.0) -> np.ndarray:
    """Per-sample gain that brings ``peak`` (per-sample peak envelope) under ``aim`` (linear)."""
    window = max(1, int(round(lookahead_ms / 1000 * fs)))
    size = max(1, int(round(HOLD_MS / 1000 * fs))) + window + 1
    need = np.minimum(1.0, aim / np.maximum(peak, 1e-12))
    # the lowest gain over [n − hold, n + look-ahead], then smoothed with the look-ahead window:
    # it is down before the peak it protects, and stays down over a sub-bass half-cycle
    held = minimum_filter1d(need, size=size, origin=size // 2 - window, mode="nearest")
    attack = np.minimum(uniform_filter1d(held, size=window, mode="nearest"), held)
    return np.minimum(attack, _release(held, fs, release_ms))


def limit(x: np.ndarray, fs: float, ceiling_dbtp: float = -1.0, lookahead_ms: float = 1.5,
          release_ms: float = 80.0) -> LimiterResult:
    x = x if x.ndim == 2 else x[:, None]
    ceiling = 10 ** (ceiling_dbtp / 20)
    aim = 10 ** ((ceiling_dbtp - AIM_DB) / 20)
    out = x.copy()
    total = np.ones(x.shape[0])
    peak = _peaks(out, fs)
    for _ in range(3):
        if peak.max() <= ceiling:
            break
        gain = gain_for(peak, fs, aim, lookahead_ms, release_ms)
        out = out * gain[:, None]
        total *= gain
        peak = _peaks(out, fs)
    top = float(peak.max())
    return LimiterResult(out, 20 * math.log10(max(total.min(), 1e-12)),
                         20 * math.log10(top) if top > 0 else -math.inf)
