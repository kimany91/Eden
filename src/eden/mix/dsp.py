"""Audio processing used by Eden's mix (offline, float64, stereo or mono).

Every processor leaves the signal untouched when its amount is zero, so that
"Eden at 0 %" gives back FL Studio's render exactly.

* filters: RBJ biquads (high-pass, peaking), applied causally like an
  analog-style EQ;
* compressor: feed-forward, linked stereo, gain computed on 1 ms frames
  then interpolated, with look-ahead (possible because Eden works offline);
* de-esser and vocal-space dip: the signal is split into a band and its
  exact complement (zero-phase filter, band + rest == input), and only the
  band's gain moves.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import butter, lfilter, sosfilt, sosfiltfilt

FRAME_S = 0.001


def _biquad(b: list[float], a: list[float]) -> np.ndarray:
    return np.array([[*(np.array(b) / a[0]), 1.0, a[1] / a[0], a[2] / a[0]]])


def highpass_sos(fs: float, f0: float, q: float = 0.7071) -> np.ndarray:
    w0 = 2 * math.pi * f0 / fs
    alpha = math.sin(w0) / (2 * q)
    cos = math.cos(w0)
    return _biquad([(1 + cos) / 2, -(1 + cos), (1 + cos) / 2], [1 + alpha, -2 * cos, 1 - alpha])


def peaking_sos(fs: float, f0: float, q: float, gain_db: float) -> np.ndarray:
    a = 10 ** (gain_db / 40)
    w0 = 2 * math.pi * f0 / fs
    alpha = math.sin(w0) / (2 * q)
    cos = math.cos(w0)
    return _biquad([1 + alpha * a, -2 * cos, 1 - alpha * a], [1 + alpha / a, -2 * cos, 1 - alpha / a])


def apply_sos(x: np.ndarray, sos: np.ndarray) -> np.ndarray:
    return sosfilt(sos, x, axis=0)


def _frames(x: np.ndarray, fs: float) -> tuple[np.ndarray, int]:
    """Mean square of each 1 ms frame (all channels together)."""
    size = max(1, int(round(FRAME_S * fs)))
    n = x.shape[0] // size
    mono = np.mean(x[: n * size] ** 2, axis=1) if x.ndim == 2 else x[: n * size] ** 2
    ms = mono.reshape(n, size).mean(axis=1) if n else np.zeros(0)
    return ms, size


def _smooth(gain_db: np.ndarray, attack_frames: float, release_frames: float) -> np.ndarray:
    """Attack/release smoothing of a gain-reduction curve (negative dB values)."""
    att = math.exp(-1 / max(attack_frames, 1e-9))
    rel = math.exp(-1 / max(release_frames, 1e-9))
    out = np.empty_like(gain_db)
    state = 0.0
    for i, target in enumerate(gain_db):
        coef = att if target < state else rel  # going down = more reduction = attack
        state = coef * state + (1 - coef) * target
        out[i] = state
    return out


def _to_samples(frame_gain_db: np.ndarray, size: int, length: int) -> np.ndarray:
    if frame_gain_db.size == 0:
        return np.ones(length)
    centers = (np.arange(frame_gain_db.size) + 0.5) * size
    db = np.interp(np.arange(length), centers, frame_gain_db)
    return 10 ** (db / 20)


def _apply_gain(x: np.ndarray, gain: np.ndarray) -> np.ndarray:
    return x * (gain[:, None] if x.ndim == 2 else gain)


def compressor_gain_db(x: np.ndarray, fs: float, threshold_db: float, ratio: float,
                       attack_ms: float = 8.0, release_ms: float = 140.0, knee_db: float = 6.0,
                       detector_ms: float = 5.0) -> tuple[np.ndarray, int]:
    """Gain reduction per 1 ms frame (dB, ≤ 0) and the frame size in samples."""
    ms, size = _frames(x, fs)
    if ms.size == 0 or ratio <= 1:
        return np.zeros(ms.size), size
    coef = math.exp(-1 / max(detector_ms / (FRAME_S * 1000), 1e-9))
    smoothed = lfilter([1 - coef], [1, -coef], ms)
    level = 10 * np.log10(np.maximum(smoothed, 1e-20))
    over = level - threshold_db
    slope = 1 - 1 / ratio
    gr = np.where(over > 0, -slope * over, 0.0)
    if knee_db > 0:
        in_knee = np.abs(over) < knee_db / 2
        gr[in_knee] = -slope * (over[in_knee] + knee_db / 2) ** 2 / (2 * knee_db)
    frame_ms = FRAME_S * 1000
    gr = _smooth(gr, attack_ms / frame_ms, release_ms / frame_ms)
    lookahead = int(round(attack_ms / frame_ms))
    if lookahead:
        gr = np.concatenate([gr[lookahead:], np.zeros(lookahead)])
    return gr, size


def compress(x: np.ndarray, fs: float, threshold_db: float, ratio: float, **kw) -> np.ndarray:
    if ratio <= 1:
        return x
    gr, size = compressor_gain_db(x, fs, threshold_db, ratio, **kw)
    return _apply_gain(x, _to_samples(gr, size, x.shape[0]))


def split_band(x: np.ndarray, fs: float, low_hz: float | None, high_hz: float | None
               ) -> tuple[np.ndarray, np.ndarray]:
    """(band, rest) with band + rest == x exactly (zero-phase Butterworth band)."""
    if low_hz and high_hz:
        sos = butter(2, [low_hz, high_hz], btype="bandpass", fs=fs, output="sos")
    elif low_hz:
        sos = butter(4, low_hz, btype="highpass", fs=fs, output="sos")
    else:
        sos = butter(4, high_hz, btype="lowpass", fs=fs, output="sos")
    band = sosfiltfilt(sos, x, axis=0)
    return band, x - band


def band_levels_db(x: np.ndarray, fs: float) -> tuple[np.ndarray, int]:
    ms, size = _frames(x, fs)
    return 10 * np.log10(np.maximum(ms, 1e-20)), size


def deess(x: np.ndarray, fs: float, threshold_db: float, max_reduction_db: float,
          ratio: float = 4.0, low_hz: float = 4500.0) -> np.ndarray:
    """Reduce the sibilance band only when it exceeds ``threshold_db`` (1 ms frames)."""
    if max_reduction_db <= 0:
        return x
    high, rest = split_band(x, fs, low_hz, None)
    level, size = band_levels_db(high, fs)
    gr = np.clip(-(level - threshold_db) * (1 - 1 / ratio), -max_reduction_db, 0.0)
    gr = _smooth(gr, 1.0, 60.0)
    return rest + _apply_gain(high, _to_samples(gr, size, x.shape[0]))


def activity_envelope(x: np.ndarray, fs: float, threshold_db: float,
                      attack_ms: float = 30.0, release_ms: float = 300.0) -> tuple[np.ndarray, int]:
    """0..1 per 1 ms frame: how much ``x`` is currently sounding (above threshold)."""
    level, size = band_levels_db(x, fs)
    on = (level > threshold_db).astype(float)
    frame_ms = FRAME_S * 1000
    att = math.exp(-1 / (attack_ms / frame_ms))
    rel = math.exp(-1 / (release_ms / frame_ms))
    out = np.empty_like(on)
    state = 0.0
    for i, target in enumerate(on):
        coef = att if target > state else rel
        state = coef * state + (1 - coef) * target
        out[i] = state
    return out, size


def dip_band_when(x: np.ndarray, fs: float, envelope: np.ndarray, size: int, depth_db: float,
                  low_hz: float = 1500.0, high_hz: float = 4000.0) -> np.ndarray:
    """Lower one band of ``x`` by up to ``depth_db`` while ``envelope`` is 1."""
    if depth_db <= 0:
        return x
    band, rest = split_band(x, fs, low_hz, high_hz)
    gain_db = -depth_db * envelope
    return rest + _apply_gain(band, _to_samples(gain_db, size, x.shape[0]))
