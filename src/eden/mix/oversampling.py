"""Oversampling for true-peak measurement, limiting and waveshaping.

True peak: the waveform a converter would reconstruct between the samples
is computed by ideal band-limited interpolation (zero-padding the spectrum
of overlapping blocks) at 8×: no filter roll-off near Nyquist, so bright
transients (hats, clicks) are not under-read the way a short interpolation
filter does it. Between the 8 points the waveform can still rise up to
0.17 dB higher (a full-scale tone at the Nyquist frequency), so the largest
point of each sample's interval is refined by a parabola through it and its
two neighbours (0.005 dB left on that tone): the reading is the peak of the
continuous waveform, within 0.01 dB of a 64× reference on noise, clipped
waves and masters.

Loudness meters read the true peak on a short interpolation filter's grid
instead; its ripple can read a little above the continuous peak.
``meter_peak`` reproduces libebur128's reading (4× under 96 kHz, 2× under
192 kHz, a 49-tap Hann-windowed sinc). FFmpeg's ebur128 and loudnorm
filters read differently: they resample to 192 kHz first (swresample), and
can show up to about 0.3 dB more than both of these readings.

Waveshaping (saturation, soft clip): the signal runs at 4× or 8× the sample
rate with a long Kaiser-windowed sinc whose cutoff sits under the original
Nyquist frequency, so the harmonics a waveshaper creates there are removed
before coming back down (aliasing). Only the change the waveshaper makes
goes through the filters.

Signals are processed in float32 and in blocks, so memory stays bounded on
a full song; each block carries enough context on both sides that the
result matches processing the whole signal at once: exactly for the
waveshapers, whose filter is short, and within a few thousandths of a dB
for the true peak, whose ideal interpolation never quite ends.
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
PEAK_CONTEXT = 16384  # true-peak blocks: context on each side (the ideal interpolation reaches far)
PEAK_CORE = (1 << 17) - 2 * PEAK_CONTEXT  # with its context, a block fills a 2^17 transform
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


def _continuous_max(up: np.ndarray, first: int, count: int, factor: int) -> np.ndarray:
    """Peak of the reconstructed waveform over base-rate samples ``first`` … ``first + count − 1``
    of the block ``up`` (``factor`` points per sample, all channels).

    Per channel, the largest of a sample's points is refined by the vertex of the parabola
    through it and its two neighbours when it is a local maximum (when the waveform still
    rises at the edge of the interval, the next sample's own maximum holds that peak). The
    block is circular, like the interpolation: its first point's neighbour is its last."""
    rows = np.arange(count)
    best = np.zeros(count)
    for c in range(up.shape[1]):
        column = up[:, c]
        grid = np.abs(column[first * factor:(first + count) * factor]).reshape(count, factor)
        at = grid.argmax(axis=1)
        top = grid[rows, at].astype(np.float64)
        index = (first + rows) * factor + at
        before = np.abs(column.take(index - 1, mode="wrap")).astype(np.float64)
        after = np.abs(column.take(index + 1, mode="wrap")).astype(np.float64)
        curve = before - 2 * top + after
        vertex = (top >= before) & (top >= after) & (curve < 0)
        top[vertex] -= (before[vertex] - after[vertex]) ** 2 / (8 * curve[vertex])
        np.maximum(best, top, out=best)
    return best


def peak_envelope(x: np.ndarray, factor: int = 8) -> np.ndarray:
    """Per base-rate sample: the peak of the reconstructed (continuous) waveform over that
    sample's interval, all channels together."""
    x = _two_d(x)
    n = x.shape[0]
    out = np.empty(n)
    for start, end, lo, hi in _blocks(n, PEAK_CORE, PEAK_CONTEXT):
        # the interpolation is circular: the block that reaches the end of the signal gets
        # PEAK_CONTEXT zeros after it, so its last samples do not ring against its first ones
        tail = PEAK_CONTEXT if hi == n else 0
        nfft = 1 << int(math.ceil(math.log2(hi - lo + tail)))
        spectrum = np.fft.rfft(x[lo:hi].astype(np.float32), nfft, axis=0)
        # in the longer spectrum the Nyquist bin has a mirror image: it carries half of it each,
        # or that component comes out doubled and the curve misses the samples themselves
        spectrum[-1] *= 0.5
        up = np.fft.irfft(spectrum, nfft * factor, axis=0)  # ideal interpolation (gain 1 / factor)
        out[start:end] = _continuous_max(up, start - lo, end - start, factor)
    return out * factor


def true_peak(x: np.ndarray, factor: int = 8) -> float:
    """Peak of the reconstructed (continuous) waveform (linear)."""
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
