"""Audio processing used by Eden's mix (offline, float64, stereo or mono).

Every processor leaves the signal untouched when its amount is zero, so that
"Eden at 0 %" gives back FL Studio's render exactly.

* filters: RBJ biquads (high-pass, peaking, shelves), applied causally like
  an analog-style EQ;
* compressor: feed-forward, linked stereo, gain computed on 1 ms frames
  then interpolated, with look-ahead (possible because Eden works offline),
  program-dependent release, an optional cap on the reduction and an
  optional "hold" mask for voices that carry effects FL Studio already
  printed: the gain never comes back above the phrase's mean reduction and
  is frozen there in the rests, so after make-up gain the tails keep about
  their level relative to the voice (see ``_smooth``);
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


def shelf_sos(fs: float, f0: float, gain_db: float, high: bool = True, slope: float = 1.0
              ) -> np.ndarray:
    """RBJ shelving filter: ``high`` lifts/lowers everything above ``f0``, else below."""
    a = 10 ** (gain_db / 40)
    w0 = 2 * math.pi * f0 / fs
    cos, sin = math.cos(w0), math.sin(w0)
    alpha = sin / 2 * math.sqrt((a + 1 / a) * (1 / slope - 1) + 2)
    r = 2 * math.sqrt(a) * alpha
    if high:
        b = [a * ((a + 1) + (a - 1) * cos + r), -2 * a * ((a - 1) + (a + 1) * cos),
             a * ((a + 1) + (a - 1) * cos - r)]
        den = [(a + 1) - (a - 1) * cos + r, 2 * ((a - 1) - (a + 1) * cos), (a + 1) - (a - 1) * cos - r]
    else:
        b = [a * ((a + 1) - (a - 1) * cos + r), 2 * a * ((a - 1) - (a + 1) * cos),
             a * ((a + 1) - (a - 1) * cos - r)]
        den = [(a + 1) + (a - 1) * cos + r, -2 * ((a - 1) + (a + 1) * cos), (a + 1) + (a - 1) * cos - r]
    return _biquad(b, den)


def apply_sos(x: np.ndarray, sos: np.ndarray) -> np.ndarray:
    return sosfilt(sos, x, axis=0)


def frame_matrix(x: np.ndarray, n: int, hop: int) -> np.ndarray:
    """Consecutive frames of a mono signal as rows (no copy until written to)."""
    if x.size < n:
        return np.zeros((0, n))
    return np.lib.stride_tricks.sliding_window_view(x, n)[::hop]


def autocorrelation(frames: np.ndarray, max_lag: int) -> np.ndarray:
    """Linear autocorrelation of each row for lags 0..``max_lag`` (FFT, zero-padded)."""
    n = frames.shape[1]
    nfft = 1 << int(math.ceil(math.log2(n + max_lag + 1)))
    spec = np.fft.rfft(frames, nfft, axis=1)
    return np.fft.irfft(np.abs(spec) ** 2, nfft, axis=1)[:, : max_lag + 1]


def _frames(x: np.ndarray, fs: float) -> tuple[np.ndarray, int]:
    """Mean square of each 1 ms frame (all channels together)."""
    size = max(1, int(round(FRAME_S * fs)))
    n = x.shape[0] // size
    mono = np.mean(x[: n * size] ** 2, axis=1) if x.ndim == 2 else x[: n * size] ** 2
    ms = mono.reshape(n, size).mean(axis=1) if n else np.zeros(0)
    return ms, size


def _smooth(gain_db: np.ndarray, attack_frames: float, release_frames: float,
            slow_release_frames: float | None = None, slow_after_frames: float = 0.0,
            hold: np.ndarray | None = None, power: np.ndarray | None = None) -> np.ndarray:
    """Attack/release smoothing of a gain-reduction curve (negative dB values).

    With ``slow_release_frames`` the release gets slower once the reduction
    has lasted ``slow_after_frames`` (program-dependent, like an opto
    compressor).

    ``hold`` (tail-safe mode, with ``power``, the detector's power per frame)
    marks the rests between phrases. A phrase is the stretch between two
    rests, and its mean reduction is the power-weighted mean of the gain the
    compressor would apply without ``hold``, 10·log10(Σ p·10^(g/10) / Σ p),
    over the phrase so far: how much a compressor without ``hold`` would take
    from the phrase's loudness. Inside a
    phrase the gain releases toward that mean instead of 0 dB, and over a
    rest it is frozen at the mean of the phrase before. Everything quieter
    than the threshold (an effect tail, an echo) then goes down by about the
    phrase's loudness reduction, which make-up gain gives back: the tail
    keeps about its level relative to its phrase. It still comes up a little,
    because the phrase's loud moments get more reduction than the mean, so
    the phrase loses a little more than its tail. The mean is taken on the
    gain without ``hold``, not on the output, which would only ever go down.
    """
    att = math.exp(-1 / max(attack_frames, 1e-9))
    rel = math.exp(-1 / max(release_frames, 1e-9))
    slow = math.exp(-1 / max(slow_release_frames, 1e-9)) if slow_release_frames else rel
    out = np.empty_like(gain_db)
    free = 0.0  # the gain without ``hold``
    busy = 0.0  # frames spent under reduction
    state = 0.0  # the gain with ``hold``
    weight, weighted, held = 0.0, 0.0, False  # Σ p and Σ p·10^(g/10) over the phrase so far
    for i, target in enumerate(gain_db):
        coef = att if target < free else (slow if busy > slow_after_frames else rel)
        free = coef * free + (1 - coef) * target
        # how long reduction was asked for; remembered until the gain has recovered
        busy = busy + 1 if target < -0.1 else (busy if free < -0.1 else 0.0)
        if hold is None:
            out[i] = free
            continue
        if hold[i]:
            if not held and weight > 0:
                state = 10 * math.log10(weighted / weight)
            held = True
            out[i] = state
            continue
        if held:
            weight, weighted, held = 0.0, 0.0, False
        weight += power[i]
        weighted += power[i] * 10 ** (free / 10)
        goal = min(target, 10 * math.log10(weighted / weight)) if weight > 0 else target
        coef = att if goal < state else (slow if busy > slow_after_frames else rel)
        state = coef * state + (1 - coef) * goal
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


def detector_power(x: np.ndarray, fs: float, detector_ms: float = 5.0) -> tuple[np.ndarray, int]:
    """Power per 1 ms frame as the compressor's detector sees it (one-pole smoothing over
    ``detector_ms``), and the frame size in samples."""
    ms, size = _frames(x, fs)
    coef = math.exp(-1 / max(detector_ms / (FRAME_S * 1000), 1e-9))
    return lfilter([1 - coef], [1, -coef], ms), size


def compressor_gain_db(x: np.ndarray, fs: float, threshold_db: float, ratio: float,
                       attack_ms: float = 8.0, release_ms: float = 140.0, knee_db: float = 6.0,
                       detector_ms: float = 5.0, slow_release_ms: float | None = None,
                       slow_after_ms: float = 200.0, max_reduction_db: float | None = None,
                       hold: np.ndarray | None = None) -> tuple[np.ndarray, int]:
    """Gain reduction per 1 ms frame (dB, ≤ 0) and the frame size in samples.

    ``hold``: 1 ms frames of the rests between phrases, for tail-safe mode (see ``_smooth``).
    """
    power, size = detector_power(x, fs, detector_ms)
    if power.size == 0 or ratio <= 1:
        return np.zeros(power.size), size
    level = 10 * np.log10(np.maximum(power, 1e-20))
    over = level - threshold_db
    slope = 1 - 1 / ratio
    gr = np.where(over > 0, -slope * over, 0.0)
    if knee_db > 0:
        in_knee = np.abs(over) < knee_db / 2
        gr[in_knee] = -slope * (over[in_knee] + knee_db / 2) ** 2 / (2 * knee_db)
    if max_reduction_db is not None:
        gr = np.maximum(gr, -max_reduction_db)
    frame_ms = FRAME_S * 1000
    lookahead = int(round(attack_ms / frame_ms))
    if hold is not None:
        # the curve is moved ``lookahead`` frames earlier below: frame i of the smoothing acts on
        # frame i − lookahead of the signal, so the mask and the power weighing the phrase mean
        # are moved the other way
        hold = np.concatenate([np.zeros(lookahead, dtype=bool), hold[: max(gr.size - lookahead, 0)]])
        hold = np.pad(hold, (0, max(gr.size - hold.size, 0)))
        power = np.concatenate([np.zeros(lookahead), power[: max(gr.size - lookahead, 0)]])
    gr = _smooth(gr, attack_ms / frame_ms, release_ms / frame_ms,
                 slow_release_ms / frame_ms if slow_release_ms else None, slow_after_ms / frame_ms, hold,
                 power if hold is not None else None)
    if lookahead:
        gr = np.concatenate([gr[lookahead:], np.zeros(lookahead)])
    return gr, size


def parallel_compress(x: np.ndarray, fs: float, threshold_db: float, blend: float,
                      low_hz: float = 100.0, high_hz: float = 5000.0, ratio: float = 8.0,
                      attack_ms: float = 5.0, release_ms: float = 50.0,
                      max_reduction_db: float = 15.0) -> np.ndarray:
    """Add a heavily compressed, band-limited copy of ``x`` (New York style), sample-aligned."""
    if blend <= 0:
        return x
    band, _ = split_band(x, fs, low_hz, high_hz)
    gr, size = compressor_gain_db(x, fs, threshold_db, ratio, attack_ms=attack_ms,
                                  release_ms=release_ms, max_reduction_db=max_reduction_db)
    return x + blend * _apply_gain(band, _to_samples(gr, size, x.shape[0]))


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


def deess_gain_db(x: np.ndarray, fs: float, threshold_db: float, max_reduction_db: float,
                  ratio: float = 4.0, low_hz: float = 4500.0, lookahead_ms: float = 5.0
                  ) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """(sibilance band, rest, gain reduction per 1 ms frame in dB, frame size) of a de-esser."""
    high, rest = split_band(x, fs, low_hz, None)
    level, size = band_levels_db(high, fs)
    return high, rest, deess_reduction_db(level, threshold_db, max_reduction_db, ratio, lookahead_ms), size


def deess_reduction_db(level: np.ndarray, threshold_db: float, max_reduction_db: float, ratio: float = 4.0,
                       lookahead_ms: float = 5.0) -> np.ndarray:
    """Gain reduction in dB per 1 ms frame of a de-esser whose sibilance band reads ``level`` (dB per
    frame): the band is lowered only when it exceeds ``threshold_db``."""
    gr = np.clip(-(level - threshold_db) * (1 - 1 / ratio), -max_reduction_db, 0.0)
    gr = _smooth(gr, 1.0, 60.0)
    ahead = int(round(lookahead_ms / (FRAME_S * 1000)))
    if ahead:  # the gain is already down when the 's' starts
        gr = np.minimum(gr, np.concatenate([gr[ahead:], np.zeros(ahead)]))
    return gr


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
