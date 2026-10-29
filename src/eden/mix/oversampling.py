"""Oversampling for true-peak measurement, limiting and waveshaping.

True peak: the waveform a converter would reconstruct between the samples
is computed by ideal band-limited interpolation (zero-padding the spectrum
of overlapping blocks): no filter roll-off near Nyquist, so bright
transients (hats, clicks) are not under-read the way a short interpolation
filter does it — the reading is, if anything, on the safe side.

Loudness meters read the true peak with a short interpolation filter
instead; its ripple can read a little above the ideal value. ``meter_peak``
reproduces the one of libebur128 (the meter in FFmpeg and many loudness
tools), so Eden's ceiling holds for both readings.

Waveshaping (saturation, soft clip): the signal runs at 4× or 8× the sample
rate with a long Kaiser-windowed sinc whose cutoff sits under the original
Nyquist frequency, so the harmonics a waveshaper creates there are removed
before coming back down (aliasing). Only the change the waveshaper makes
goes through the filters.

Signals are processed in float32 and in blocks, so memory stays bounded on
a full song; each block carries enough context on both sides that the
result is the same as processing the whole signal at once.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from functools import cache

import numpy as np
from scipy.signal import firwin, upfirdn

BLOCK = 1 << 16
PAD = 256  # base-rate samples of context on each side of a block (the shaping filter reaches ±32)
SHAPE = (64, 10.0)  # taps per phase, Kaiser beta
SHAPE_CUTOFF_HZ = 20500.0  # the shaper's added harmonics are kept under this (and under 93 % of Nyquist)
PEAK_CONTEXT = 4096  # true-peak blocks: context on each side, and a core that fills a 2^16 transform
PEAK_CORE = (1 << 16) - 2 * PEAK_CONTEXT
METER_TAPS = 49  # libebur128: Hann-windowed sinc, 4× under 96 kHz, 2× under 192 kHz


@cache
def _filter(factor: int, taps_per_phase: int, beta: float, cutoff: float) -> np.ndarray:
    """Low-pass at ``cutoff`` (fraction of the original Nyquist frequency), gain ``factor``."""
    half = taps_per_phase * factor // 2
    return (firwin(2 * half + 1, cutoff / factor, window=("kaiser", beta)) * factor).astype(np.float32)


def _two_d(x: np.ndarray) -> np.ndarray:
    return x[:, None] if x.ndim == 1 else x


def _cutoff(fs: float) -> float:
    return min(SHAPE_CUTOFF_HZ, 0.93 * fs / 2) / (fs / 2)


def _up(x: np.ndarray, factor: int, h: np.ndarray) -> np.ndarray:
    half = (h.size - 1) // 2
    y = upfirdn(h, x, factor, 1, axis=0)
    return y[half:half + x.shape[0] * factor]


def _down(y: np.ndarray, factor: int, n: int, h: np.ndarray) -> np.ndarray:
    h = h / factor
    half = (h.size - 1) // 2  # a multiple of ``factor`` (even taps per phase)
    padded = np.concatenate([y, np.zeros((half, y.shape[1]), dtype=y.dtype)])
    offset = half // factor  # output k is centred on input k · factor
    return upfirdn(h, padded, 1, factor, axis=0)[offset:offset + n]


def _blocks(n: int, size: int = BLOCK, pad: int = PAD):
    for start in range(0, n, size):
        end = min(n, start + size)
        yield start, end, max(0, start - pad), min(n, end + pad)


def _per_sample_max(up: np.ndarray, factor: int) -> np.ndarray:
    """Largest |value| of each base-rate sample's ``factor`` interpolated points, all channels."""
    mag = np.abs(up[:, 0])
    for c in range(1, up.shape[1]):  # column by column: much faster than a reduction over axis 1
        np.maximum(mag, np.abs(up[:, c]), out=mag)
    return mag.reshape(-1, factor).max(axis=1)


def peak_envelope(x: np.ndarray, factor: int = 8) -> np.ndarray:
    """Per base-rate sample: the largest |value| of the reconstructed waveform over that
    sample's interval (``factor`` interpolated points), all channels together."""
    x = _two_d(x)
    out = np.empty(x.shape[0])
    for start, end, lo, hi in _blocks(x.shape[0], PEAK_CORE, PEAK_CONTEXT):
        nfft = 1 << int(math.ceil(math.log2(hi - lo)))
        spectrum = np.fft.rfft(x[lo:hi].astype(np.float32), nfft, axis=0)
        up = np.fft.irfft(spectrum, nfft * factor, axis=0)  # ideal interpolation (gain 1 / factor)
        out[start:end] = _per_sample_max(up[(start - lo) * factor:(end - lo) * factor], factor)
    return out * factor


def true_peak(x: np.ndarray, factor: int = 8) -> float:
    """Highest |value| of the reconstructed waveform (linear)."""
    return float(peak_envelope(x, factor).max()) if np.size(x) else 0.0


@cache
def _meter_filter(factor: int) -> np.ndarray:
    m = np.arange(METER_TAPS) - (METER_TAPS - 1) / 2
    return (np.sinc(m / factor) * np.hanning(METER_TAPS)).astype(np.float32)


def meter_envelope(x: np.ndarray, fs: float) -> np.ndarray:
    """Per base-rate sample: the largest |value| libebur128's true-peak interpolation reads over
    that sample's interval, all channels together."""
    x = _two_d(x)
    factor = 4 if fs < 96000 else 2 if fs < 192000 else 1
    if factor == 1 or x.shape[0] == 0:
        return np.abs(x).max(axis=1) if x.shape[0] else np.zeros(0)
    h = _meter_filter(factor)
    delay = (METER_TAPS - 1) // 2
    out = np.empty(x.shape[0])
    for start, end, lo, hi in _blocks(x.shape[0]):
        up = upfirdn(h, x[lo:hi].astype(np.float32), factor, 1, axis=0)
        out[start:end] = _per_sample_max(up[(start - lo) * factor + delay:(end - lo) * factor + delay], factor)
    return out


def meter_peak(x: np.ndarray, fs: float) -> float:
    """Highest |value| as libebur128 reads the true peak (linear, all channels)."""
    return float(meter_envelope(x, fs).max()) if np.size(x) else 0.0


def shape_change(x: np.ndarray, fs: float, factor: int, func: Callable[[np.ndarray], np.ndarray]) -> np.ndarray:
    """What waveshaper ``func`` adds to ``x`` when run at ``factor``× the sample rate.

    Returned as a change (``func(u) − u``, filtered back down), so the caller
    adds it to the untouched input: where ``func`` does nothing, the signal is
    bit-exact, and only the shaping itself goes through the filters.
    """
    two_d = _two_d(x)
    h = _filter(factor, *SHAPE, _cutoff(fs))
    out = np.empty(two_d.shape)
    for start, end, lo, hi in _blocks(two_d.shape[0]):
        up = _up(two_d[lo:hi].astype(np.float32), factor, h)
        down = _down(func(up) - up, factor, hi - lo, h)
        out[start:end] = down[start - lo:end - lo]
    return out if x.ndim == 2 else out[:, 0]
