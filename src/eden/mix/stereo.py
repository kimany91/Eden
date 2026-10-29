"""Stereo image: mid/side, width, panning, mono low end and mono compatibility.

Placement of the voices follows what rap mixes do: the lead stays mono in
the centre; a pair of doubles goes wide left/right when they are real
separate takes (not copies of the lead); backs sit in pairs around the
lead; ad-libs are never centred while the lead sings — each ad-lib phrase
goes to the opposite side of the previous one. A voice the user already
spread or panned in FL Studio is left where it is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.signal import butter, resample_poly, sosfilt

from eden.mix import dsp
from eden.mix.riding import phrases_of

MONO_SIDE_DB = -20.0  # a render whose side is this far under its mid counts as mono
COPY_CORRELATION = 0.8  # a double this correlated with the lead is a copy, not another take (heuristic)


def to_stereo(x: np.ndarray) -> np.ndarray:
    return np.repeat(x[:, None], 2, axis=1) if x.ndim == 1 else (np.repeat(x, 2, axis=1) if x.shape[1] == 1 else x)


def mid_side(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    x = to_stereo(x)
    return (x[:, 0] + x[:, 1]) / 2, (x[:, 0] - x[:, 1]) / 2


def from_mid_side(mid: np.ndarray, side: np.ndarray) -> np.ndarray:
    return np.stack([mid + side, mid - side], axis=1)


def set_width(x: np.ndarray, width: float) -> np.ndarray:
    """Scale the side signal (1 = unchanged, 0 = mono, >1 = wider)."""
    mid, side = mid_side(x)
    return from_mid_side(mid, side * width)


def pan(x: np.ndarray, position: float) -> np.ndarray:
    """Constant-power pan of a (mono-summed) signal; position −1 (left) … +1 (right)."""
    mono = x.mean(axis=1) if x.ndim == 2 else x
    angle = (position + 1) * math.pi / 4
    return np.stack([mono * math.cos(angle), mono * math.sin(angle)], axis=1) * math.sqrt(2)


def balance(x: np.ndarray, position: float) -> np.ndarray:
    """Move a stereo signal towards one side without collapsing its own width."""
    x = to_stereo(x)
    left = math.sqrt(2) * math.cos((position + 1) * math.pi / 4)
    right = math.sqrt(2) * math.sin((position + 1) * math.pi / 4)
    return np.stack([x[:, 0] * left, x[:, 1] * right], axis=1)


def linkwitz_riley(fs: float, freq: float) -> tuple[np.ndarray, np.ndarray]:
    """4th-order Linkwitz-Riley low/high pair (sum is all-pass, flat magnitude)."""
    lp = butter(2, freq, btype="lowpass", fs=fs, output="sos")
    hp = butter(2, freq, btype="highpass", fs=fs, output="sos")
    return np.vstack([lp, lp]), np.vstack([hp, hp])


def mono_below(x: np.ndarray, fs: float, freq: float) -> np.ndarray:
    """Remove the side signal below ``freq`` (mono low end).

    The side's low band is taken with a zero-phase filter and subtracted: the
    mid is untouched and, above ``freq``, so is the side — the image does not
    move, only the stereo part of the lows goes.
    """
    mid, side = mid_side(x)
    low_side, _ = dsp.split_band(side, fs, None, freq)
    return from_mid_side(mid, side - low_side)


@dataclass
class StereoMeasure:
    correlation: float  # +1 mono … 0 wide … −1 out of phase
    side_ratio_db: float  # side energy relative to mid energy
    mono_loss_db: float  # loudness lost when summed to mono (energy)
    low_side_ratio_db: float  # side/mid energy below 120 Hz


def _db(a: float, b: float) -> float:
    return 10 * math.log10(a / b) if a > 0 and b > 0 else -math.inf


def measure(x: np.ndarray, fs: float, low_hz: float = 120.0) -> StereoMeasure:
    x = to_stereo(x)
    left, right = x[:, 0], x[:, 1]
    denom = math.sqrt(float(np.sum(left ** 2) * np.sum(right ** 2)))
    corr = float(np.sum(left * right) / denom) if denom else 1.0
    mid, side = mid_side(x)
    stereo_energy = float(np.sum(left ** 2) + np.sum(right ** 2)) / 2
    mono_energy = float(np.sum(((left + right) / 2) ** 2))
    lp, _ = linkwitz_riley(fs, low_hz)
    low_mid, low_side = sosfilt(lp, mid), sosfilt(lp, side)
    return StereoMeasure(
        correlation=corr,
        side_ratio_db=_db(float(np.sum(side ** 2)), float(np.sum(mid ** 2))),
        mono_loss_db=_db(mono_energy, stereo_energy),
        low_side_ratio_db=_db(float(np.sum(low_side ** 2)), float(np.sum(low_mid ** 2))),
    )


def low_band_correlation(x: np.ndarray, fs: float, cutoff: float) -> float:
    """L/R correlation of the band below ``cutoff`` (+1 mono … −1 out of phase)."""
    x = to_stereo(x)
    lp, _ = linkwitz_riley(fs, cutoff)
    low = sosfilt(lp, x, axis=0)
    denom = math.sqrt(float(np.sum(low[:, 0] ** 2) * np.sum(low[:, 1] ** 2)))
    return float(np.sum(low[:, 0] * low[:, 1]) / denom) if denom > 0 else 1.0


def is_mono(x: np.ndarray, fs: float) -> bool:
    return measure(x, fs).side_ratio_db < MONO_SIDE_DB


def copy_correlation(double: np.ndarray, lead: np.ndarray, fs: float, max_lag_ms: float = 40.0) -> float:
    """How much ``double`` is a copy of ``lead``: highest normalised cross-correlation within
    ±``max_lag_ms`` (Haas-style delayed copies included), over the moments the double sounds
    (an "in-out" double repeats only some words of the lead)."""
    factor = max(1, int(fs // 11025))  # voice content below 5 kHz is enough to recognise a copy
    d = resample_poly(double.mean(axis=1) if double.ndim == 2 else double, 1, factor)
    lv = resample_poly(lead.mean(axis=1) if lead.ndim == 2 else lead, 1, factor)
    n = min(d.size, lv.size)
    d, lv = d[:n], lv[:n]
    rate = fs / factor
    level, size = dsp.band_levels_db(d, rate)
    if level.size == 0:
        return 0.0
    active = np.repeat(level > float(np.percentile(level, 95)) - 30.0, size)
    mask = np.pad(active, (0, max(0, n - active.size)))[:n]
    dm, lm = d * mask, lv * mask
    denom = math.sqrt(float(np.dot(dm, dm) * np.dot(lm, lm)))
    if denom <= 0:
        return 0.0
    nfft = 1 << int(math.ceil(math.log2(2 * n)))
    xc = np.fft.irfft(np.fft.rfft(dm, nfft) * np.conj(np.fft.rfft(lm, nfft)), nfft)
    lag = int(max_lag_ms / 1000 * rate)
    near = np.concatenate([xc[:lag + 1], xc[-lag:]]) if lag else xc[:1]
    return float(np.max(np.abs(near)) / denom)


def alternate_pan(x: np.ndarray, fs: float, position: float, gap_s: float = 0.25) -> np.ndarray:
    """Each phrase of ``x`` goes to the opposite side of the previous one (±``position``).

    The move happens in the middle of the rest between two phrases, with a
    50 ms fade: a phrase never starts in the centre or slides during a word.
    """
    level, size = dsp.band_levels_db(x, fs)
    if level.size == 0:
        return to_stereo(x)
    active = level > float(np.percentile(level, 95)) - 30.0
    phrases = phrases_of(active, max(1, int(gap_s / dsp.FRAME_S)))
    side = np.ones(level.size)
    sign = 1.0
    for i, (s, _) in enumerate(phrases):
        start = (phrases[i - 1][1] + s) // 2 if i else 0  # switch in the middle of the rest before
        side[start:] = sign
        sign = -sign
    ramp = max(1, int(0.05 / dsp.FRAME_S))
    side = np.convolve(np.pad(side, (ramp // 2, ramp - ramp // 2 - 1), mode="edge"), np.ones(ramp) / ramp, mode="valid")
    centers = (np.arange(side.size) + 0.5) * size
    pos = np.interp(np.arange(x.shape[0]), centers, side) * position
    mono = x.mean(axis=1) if x.ndim == 2 else x
    angle = (pos + 1) * math.pi / 4
    return np.stack([mono * np.cos(angle), mono * np.sin(angle)], axis=1) * math.sqrt(2)


@dataclass
class Placement:
    key: str
    label: str
    position: float  # −1 left … +1 right; 0 = centre (unchanged)
    alternate: bool = False  # ad-libs: phrases alternate between −position and +position
    reason: str = ""
    notes: list[str] = field(default_factory=list)


def plan_placement(voices: list[tuple[str, str, str, np.ndarray]], copies: dict[str, float], fs: float,
                   k: float) -> list[Placement]:
    """Pan positions for (key, label, role, audio) voices; mono renders only, leads untouched.
    ``copies``: how much each double copies the lead (``copy_correlation``)."""
    out: list[Placement] = []
    if k <= 0:
        return out
    doubles = [v for v in voices if v[2] == "double" and is_mono(v[3], fs)]
    backs = [v for v in voices if v[2] == "back_vocal" and is_mono(v[3], fs)]
    adlibs = [v for v in voices if v[2] == "adlib" and is_mono(v[3], fs)]
    real_doubles = []
    for key, label, _, _ in doubles:
        corr = copies.get(key, 0.0)
        if corr > COPY_CORRELATION:
            out.append(Placement(key, label, 0.0, reason=f"copie de la voix principale (corrélation {corr:.2f}) : "
                                 "laissée au centre, l'écarter créerait un filtrage en peigne"))
        else:
            real_doubles.append((key, label))
    paired = len(real_doubles) // 2 * 2
    for i, (key, label) in enumerate(real_doubles[:paired]):
        out.append(Placement(key, label, (0.85 if i % 2 == 0 else -0.85) * k,
                             reason="doubles en paire : une à gauche, une à droite, larges"))
    for key, label in real_doubles[paired:]:
        out.append(Placement(key, label, 0.0, reason="double seule : au centre, sous la voix principale"))
    for i, (key, label, _, _) in enumerate(backs):
        pos = (0.55 if i % 2 == 0 else -0.55) if len(backs) >= 2 else 0.4
        out.append(Placement(key, label, pos * k, reason="chœurs de part et d'autre de la voix principale"))
    for key, label, _, _ in adlibs:
        out.append(Placement(key, label, 0.5 * k, alternate=True,
                             reason="ad-libs jamais au centre : chaque phrase change de côté"))
    return out


def place(x: np.ndarray, fs: float, p: Placement) -> np.ndarray:
    if p.alternate:
        return alternate_pan(x, fs, p.position)
    return pan(x, p.position) if p.position else to_stereo(x)
