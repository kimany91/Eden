"""True-peak limiter for the final master (offline, look-ahead, linked stereo).

1. Peaks are found on the reconstructed, continuous waveform (ideal 8×
   interpolation refined between its points, ``oversampling``), and as
   libebur128 reads them (its short interpolation filter can read a little
   higher): the ceiling holds for both readings, not only for the samples.
2. The gain each sample needs is held from the look-ahead window before a
   peak to 20 ms after it (sliding minimum), so it does not ripple inside
   an 808 cycle (distortion).
3. The recovery (release) follows a smooth exponential on 1 ms frames.
   The result is averaged over the look-ahead window that ends at each
   sample: the gain ramps down ahead of a peak over at least the look-ahead
   (1.5 ms), never in one step (a click).
4. The output is measured again; if it is not at least 0.01 dB under the
   ceiling (what the continuous-peak reading may miss), the pass is repeated
   on the remaining excess (the gain aims 0.04 dB under the ceiling, so this
   is rare). That last measurement is the reported true peak.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import minimum_filter1d, uniform_filter1d

from eden.mix.oversampling import meter_envelope, peak_envelope

OVERSAMPLE = 8
HOLD_MS = 20.0  # a 40 Hz half-cycle is 12.5 ms: shorter, the gain would ripple inside each cycle
AIM_DB = 0.04  # the gain aims this far under the ceiling, so one pass is usually enough
READ_DB = 0.01  # the output stays this far under it: the most the continuous-peak reading can miss


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
    # the lowest gain over [n − hold, n + look-ahead]: it is down before the peak it protects,
    # and stays down over a sub-bass half-cycle
    held = minimum_filter1d(need, size=size, origin=size // 2 - window, mode="nearest")
    # with the recovery, then averaged over the samples n − look-ahead + 1 … n: each of those
    # already covers need[n], so no peak gets through, and no sample's gain moves by more than
    # the reduction divided by the look-ahead window
    gain = np.minimum(held, _release(held, fs, release_ms))
    return uniform_filter1d(gain, size=window, origin=(window - 1) // 2, mode="nearest")


def limit(x: np.ndarray, fs: float, ceiling_dbtp: float = -1.0, lookahead_ms: float = 1.5,
          release_ms: float = 80.0) -> LimiterResult:
    out = x if x.ndim == 2 else x[:, None]  # never written to: each pass makes a new array
    highest = 10 ** ((ceiling_dbtp - READ_DB) / 20)  # the highest reading accepted
    aim = 10 ** ((ceiling_dbtp - AIM_DB) / 20)
    total = np.ones(out.shape[0])
    peak = _peaks(out, fs)
    for _ in range(3):
        if peak.max() <= highest:
            break
        gain = gain_for(peak, fs, aim, lookahead_ms, release_ms)
        out = out * gain[:, None]
        total *= gain
        peak = _peaks(out, fs)
    top = float(peak.max())
    return LimiterResult(out, 20 * math.log10(max(total.min(), 1e-12)),
                         20 * math.log10(top) if top > 0 else -math.inf)
