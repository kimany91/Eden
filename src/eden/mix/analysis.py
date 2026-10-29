"""Measurements Eden bases its mix decisions on.

All values are measured on FL Studio's renders (the voice *with* its FL
effects), so Eden reacts to what the voice really sounds like after the
user's own chain, and does not correct what is already right.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.signal import stft, welch

from eden.mix.dsp import autocorrelation, band_levels_db, frame_matrix, split_band
from eden.mix.loudness import block_loudness, gated_loudness, loudness_of_blocks

ACTIVE_RANGE_DB = 35.0  # 1 ms frames this close to the loud parts count as "singing"
ANALYSIS_LOW_HZ, ANALYSIS_HIGH_HZ = 150.0, 8000.0


@dataclass
class Resonance:
    freq_hz: float
    excess_db: float


@dataclass
class Level:
    lufs: float
    active_blocks: np.ndarray = field(repr=False)  # 400 ms blocks (100 ms apart) where it sounds


def level_of(x: np.ndarray, fs: float) -> Level:
    """Integrated loudness and the blocks within 10 LU of it (where the voice is singing)."""
    blocks = block_loudness(x, fs)
    lufs = gated_loudness(blocks)
    return Level(lufs, np.isfinite(blocks) & (blocks > lufs - 10))


@dataclass
class VocalMeasure:
    loudness_lufs: float
    active_share: float  # fraction of the song where the voice sounds
    low_energy_db: float  # energy below 70 Hz relative to the whole voice
    low_120_db: float  # energy below 120 Hz relative to the whole voice
    mud_db: float  # 200–500 Hz relative to 1–4 kHz
    resonances: list[Resonance] = field(default_factory=list)
    vowel_level_db: float = -math.inf  # typical level of the voiced parts (1 ms frames)
    sibilant_excess_db: float = -math.inf  # loud 's' sounds relative to the vowels
    sibilant_share: float = 0.0  # share of sung time where 's' sounds dominate
    dynamic_spread_db: float = 0.0  # P90 − P10 of the 400 ms loudness inside phrases (rests excluded)
    crest_db: float = 0.0  # peak to RMS while singing
    sung_p70_db: float = -math.inf  # typical level of the sung moments (1 ms frames)
    lowest_f0_hz: float | None = None  # lowest sustained pitch of the voice
    sibilant_peak_hz: float | None = None  # where the 's' sounds have their energy
    low_mid_hz: float = 300.0  # centre of the low-mid build-up (proximity, boxiness)
    low_mid_excess_db: float = 0.0  # how much that region sticks out of the voice's envelope
    air_db: float = -math.inf  # energy above 8 kHz relative to 2–5 kHz, on vowels only
    active_blocks: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool), repr=False)


def mono(x: np.ndarray) -> np.ndarray:
    return x.mean(axis=1) if x.ndim == 2 else x


def active_frames(x: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray, int]:
    level, size = band_levels_db(x, fs)
    if level.size == 0:
        return level, np.zeros(0, dtype=bool), size
    top = np.percentile(level, 95)
    return level, level > max(-60.0, top - ACTIVE_RANGE_DB), size


def sung_samples(x: np.ndarray, active: np.ndarray, size: int) -> np.ndarray:
    """The voice with its silences removed (mono)."""
    sig = mono(x)
    mask = np.repeat(active, size)
    sung = sig[: mask.size][mask]
    return sung if sung.size >= 4096 else sig


def _psd_db(sung: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
    nper = min(8192, max(256, 1 << int(math.log2(max(sung.size, 256)))))
    freqs, psd = welch(sung, fs=fs, nperseg=nper)
    return freqs, 10 * np.log10(np.maximum(psd, 1e-30))


def _band_db(freqs: np.ndarray, psd_db: np.ndarray, lo: float, hi: float) -> float:
    sel = (freqs >= lo) & (freqs < hi)
    if not sel.any():
        return -math.inf
    return 10 * math.log10(np.sum(10 ** (psd_db[sel] / 10)) + 1e-30)


def _excess_over_octave(f: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Spectrum minus its one-octave smoothed version (dB)."""
    lin = 10 ** (p / 10)
    smooth = np.empty_like(p)
    for i, fc in enumerate(f):
        win = (f >= fc / 2 ** 0.5) & (f <= fc * 2 ** 0.5)
        smooth[i] = 10 * math.log10(np.mean(lin[win]))
    return p - smooth


def _levinson(r: np.ndarray, order: int) -> np.ndarray:
    """Linear-prediction polynomials [1, a1 … a_order] of every row of autocorrelations ``r``."""
    a = np.zeros((r.shape[0], order + 1))
    a[:, 0] = 1.0
    err = r[:, 0].copy()
    for i in range(1, order + 1):
        acc = r[:, i] + np.sum(a[:, 1:i] * r[:, i - 1:0:-1], axis=1)
        k = -acc / err
        a[:, 1:i] = a[:, 1:i] + k[:, None] * a[:, i - 1:0:-1]
        a[:, i] = k
        err = err * (1 - k * k)
    return a


MAX_ENVELOPE_FRAMES = 2000  # evenly spread over the song: plenty for an average


def spectral_envelope(sung: np.ndarray, fs: float, frame_s: float = 0.03, nfft: int = 2048
                      ) -> tuple[np.ndarray, np.ndarray]:
    """Average LPC envelope of the voice (dB): the shape of the sound, without the notes.

    Linear prediction follows the resonances of the voice and of the room,
    not the harmonics of the sung pitch; averaging over many syllables then
    flattens the moving vowel formants and keeps what never moves.
    """
    order = int(fs / 1000) + 4
    n = int(frame_s * fs)
    freqs = np.linspace(0, fs / 2, nfft, endpoint=False)
    frames = frame_matrix(sung, n, n)
    if frames.shape[0] > MAX_ENVELOPE_FRAMES:
        frames = frames[np.linspace(0, frames.shape[0] - 1, MAX_ENVELOPE_FRAMES).astype(int)]
    frames = frames * np.hanning(n)
    r = autocorrelation(frames, order)
    r = r[r[:, 0] >= 1e-10]
    if r.shape[0] == 0:
        return freqs, np.zeros(nfft)
    r[:, 0] *= 1 + 1e-9
    a = _levinson(r, order)
    a = a[np.all(np.isfinite(a), axis=1)]
    if a.shape[0] == 0:
        return freqs, np.zeros(nfft)
    env = -20 * np.log10(np.abs(np.fft.rfft(a, 2 * nfft, axis=1)[:, :nfft]) + 1e-12)
    return freqs, np.mean(env - env.max(axis=1, keepdims=True), axis=0)


def find_resonances(freqs: np.ndarray, env: np.ndarray, min_excess_db: float = 4.5,
                    max_count: int = 3) -> list[Resonance]:
    """Fixed bumps in the voice's average envelope (room or microphone resonances).

    The threshold is strict on purpose: a missed resonance costs less than
    notching notes the artist wants (Auto-Tune holding the same notes can
    leave small bumps of its own).
    """
    sel = (freqs >= ANALYSIS_LOW_HZ) & (freqs <= ANALYSIS_HIGH_HZ)
    f = freqs[sel]
    excess = _excess_over_octave(f, env[sel])
    found: list[Resonance] = []
    for i in np.argsort(excess)[::-1]:
        if excess[i] < min_excess_db or len(found) >= max_count:
            break
        if all(abs(math.log2(f[i] / r.freq_hz)) > 1 / 3 for r in found):
            found.append(Resonance(float(f[i]), float(excess[i])))
    return sorted(found, key=lambda r: r.freq_hz)


def lowest_f0(sung: np.ndarray, fs: float, fmin: float = 60.0, fmax: float = 500.0,
              frame_s: float = 0.04) -> float | None:
    """Lowest sustained pitch (5th percentile of the clearly periodic frames), in Hz."""
    n = int(frame_s * fs)
    lag_min, lag_max = int(fs / fmax), int(fs / fmin)
    if sung.size < 10 * n or lag_max >= n:
        return None
    frames = frame_matrix(sung, n, n)
    frames = frames - frames.mean(axis=1, keepdims=True)
    ac = autocorrelation(frames, lag_max)
    ac = ac[ac[:, 0] >= 1e-10]
    if ac.shape[0] == 0:
        return None
    ac = ac / ac[:, :1]
    region = ac[:, lag_min:lag_max + 1]
    lags = lag_min + np.argmax(region, axis=1)
    clear = region.max(axis=1) > 0.6
    found = fs / lags[clear]
    return float(np.percentile(found, 5)) if found.size >= 10 else None


def _frames_psd(x: np.ndarray, fs: float, frames: np.ndarray, size: int) -> tuple[np.ndarray, np.ndarray]:
    """Welch spectrum (dB) of the 1 ms frames selected by ``frames``."""
    sig = mono(x)
    mask = np.repeat(frames, size)
    chosen = sig[: mask.size][mask]
    if chosen.size < 4096:
        return np.zeros(0), np.zeros(0)
    return _psd_db(chosen, fs)


def sibilant_peak(x: np.ndarray, fs: float, s_frames: np.ndarray, size: int) -> float | None:
    """Frequency of the 's' sounds' spectral peak (3–10 kHz), from the 's' frames only."""
    freqs, psd = _frames_psd(x, fs, s_frames, size)
    sel = (freqs >= 3000) & (freqs <= 10000)
    if not sel.any():
        return None
    return float(freqs[sel][np.argmax(psd[sel])])


def air(x: np.ndarray, fs: float, vowel_frames: np.ndarray, size: int) -> float:
    """Energy above 8 kHz relative to 2–5 kHz on the vowels (negative: dull top end)."""
    freqs, psd = _frames_psd(x, fs, vowel_frames, size)
    if freqs.size == 0:
        return -math.inf
    return _band_db(freqs, psd, 8000, min(16000, fs / 2)) - _band_db(freqs, psd, 2000, 5000)


def low_mid_buildup(freqs: np.ndarray, env: np.ndarray) -> tuple[float, float]:
    """(centre, excess dB) of the strongest bump of the envelope between 150 and 500 Hz."""
    sel = (freqs >= 100) & (freqs <= 1000)
    excess = _excess_over_octave(freqs[sel], env[sel])
    f = freqs[sel]
    zone = (f >= 150) & (f <= 500)
    i = int(np.argmax(np.where(zone, excess, -math.inf)))
    return float(f[i]), float(max(excess[i], 0.0))


def sibilance(x: np.ndarray, fs: float, level: np.ndarray, active: np.ndarray
              ) -> tuple[float, float, float]:
    """(vowel level, loud 's' minus vowels, share of 's') from 1 ms frames.

    A frame is an 's' when the band above 4.5 kHz carries most of its energy,
    a vowel when that band is far below. Piercing sibilants are 's' sounds
    nearly as loud as the vowels or louder.
    """
    s_frames, vowels = sibilant_frames(x, fs, level, active)
    full = level[: s_frames.size]
    if not vowels.any():
        return -math.inf, -math.inf, 0.0
    vowel = float(np.percentile(full[vowels], 75))
    if not s_frames.any():
        return vowel, -math.inf, 0.0
    return vowel, float(np.percentile(full[s_frames], 90)) - vowel, \
        float(s_frames.sum() / active[: s_frames.size].sum())


def sibilant_frames(x: np.ndarray, fs: float, level: np.ndarray, active: np.ndarray
                    ) -> tuple[np.ndarray, np.ndarray]:
    """('s' frames, vowel frames) among the active 1 ms frames."""
    high, _ = split_band(mono(x), fs, 4500.0, None)
    hlevel, _ = band_levels_db(high, fs)
    n = min(hlevel.size, level.size)
    full, hi, act = level[:n], hlevel[:n], active[:n]
    return act & (hi - full > -3.0), act & (hi - full < -15.0)


def _inside_phrases(active: np.ndarray, size: int, fs: float, count: int) -> np.ndarray:
    """400 ms loudness blocks (100 ms apart) whose 1 ms frames are at least 90 % sung."""
    cumulative = np.concatenate([[0], np.cumsum(active)])
    block, step = int(round(0.4 * fs / size)), int(round(0.1 * fs / size))
    starts = np.arange(count) * step
    ends = np.minimum(starts + block, active.size)
    starts = np.minimum(starts, active.size)
    sung = (cumulative[ends] - cumulative[starts]) / np.maximum(ends - starts, 1)
    return sung >= 0.9


def measure_vocal(x: np.ndarray, fs: float) -> VocalMeasure:
    level, active, size = active_frames(x, fs)
    if not active.any():
        return VocalMeasure(-math.inf, 0.0, -math.inf, -math.inf, 0.0)
    sung = sung_samples(x, active, size)
    freqs, psd = _psd_db(sung, fs)
    total = _band_db(freqs, psd, 20, fs / 2)
    blocks = block_loudness(x, fs)
    lufs = gated_loudness(blocks)
    active_blocks = np.isfinite(blocks) & (blocks > lufs - 10)
    sung_blocks = blocks[active_blocks & _inside_phrases(active, size, fs, blocks.size)]

    vowel_level, sib_excess, sib_share = sibilance(x, fs, level, active)
    s_frames, vowel_frames = sibilant_frames(x, fs, level, active)
    long_enough = sung.size >= 4 * fs
    envelope = spectral_envelope(sung, fs) if long_enough else None
    low_mid_hz, low_mid_excess = low_mid_buildup(*envelope) if envelope else (300.0, 0.0)

    sung_level = level[active]
    rms_db = 10 * math.log10(np.mean(10 ** (sung_level / 10)))
    peak_db = 20 * math.log10(max(float(np.max(np.abs(x))), 1e-12))
    return VocalMeasure(
        loudness_lufs=lufs,
        active_share=float(active.mean()),
        low_energy_db=_band_db(freqs, psd, 20, 70) - total,
        low_120_db=_band_db(freqs, psd, 20, 120) - total,
        mud_db=_band_db(freqs, psd, 200, 500) - _band_db(freqs, psd, 1000, 4000),
        resonances=find_resonances(*envelope) if envelope else [],
        vowel_level_db=vowel_level,
        sibilant_excess_db=sib_excess,
        sibilant_share=sib_share,
        dynamic_spread_db=float(np.percentile(sung_blocks, 90) - np.percentile(sung_blocks, 10))
        if sung_blocks.size >= 4 else 0.0,
        crest_db=peak_db - rms_db,
        sung_p70_db=float(np.percentile(sung_level, 70)),
        lowest_f0_hz=lowest_f0(sung, fs),
        sibilant_peak_hz=sibilant_peak(x, fs, s_frames, size),
        low_mid_hz=low_mid_hz,
        low_mid_excess_db=low_mid_excess,
        air_db=air(x, fs, vowel_frames, size),
        active_blocks=active_blocks,
    )


def balance_against(voice: Level, other: np.ndarray, fs: float) -> float:
    """Voice loudness minus the loudness of ``other`` while the voice sounds (dB)."""
    other_lufs = loudness_of_blocks(other, fs, voice.active_blocks)
    if not math.isfinite(other_lufs) or not math.isfinite(voice.lufs):
        return math.inf
    return voice.lufs - other_lufs


# ANSI S3.5-1997 octave-band importance for speech intelligibility (Annex C example),
# centre 250 Hz … 8 kHz; the 1–4 kHz octaves carry about 72 % of the weight.
SII_OCTAVE_WEIGHTS = {250: 0.0617, 500: 0.1671, 1000: 0.2373, 2000: 0.2648, 4000: 0.2142, 8000: 0.0549}


@dataclass
class BandMasking:
    low_hz: float
    high_hz: float
    masking_db: float  # other minus voice in this band while the voice sings
    weight: float  # importance of the band for the words (SII)


def _band_power(x: np.ndarray, fs: float, mask: np.ndarray, edges: list[tuple[float, float]]
                ) -> np.ndarray:
    """Mean power per band over the STFT frames that fall in the selected 400 ms blocks."""
    two_d = x if x.ndim == 2 else x[:, None]
    nper = 4096
    freqs, times, z = stft(two_d, fs=fs, nperseg=nper, noverlap=nper - nper // 4, axis=0, boundary=None)
    power = np.sum(np.abs(z) ** 2, axis=1)  # (bins, frames), channels added like BS.1770
    block = np.clip(np.round((times - 0.2) / 0.1).astype(int), 0, max(mask.size - 1, 0))
    chosen = mask[block] if mask.size else np.zeros(times.size, dtype=bool)
    if not chosen.any():
        return np.full(len(edges), np.nan)
    mean = power[:, chosen].mean(axis=1)
    return np.array([mean[(freqs >= lo) & (freqs < hi)].sum() for lo, hi in edges])


def band_masking(vocal: np.ndarray, other: np.ndarray, fs: float, mask: np.ndarray
                 ) -> list[BandMasking]:
    """How much ``other`` covers the voice in each 1/3-octave band while the voice sings,
    weighted by the band's importance for intelligibility (SII)."""
    bands = []
    for centre, weight in SII_OCTAVE_WEIGHTS.items():
        for third in (-1, 0, 1):
            fc = centre * 2 ** (third / 3)
            lo, hi = fc / 2 ** (1 / 6), fc * 2 ** (1 / 6)
            if hi < fs / 2:
                bands.append((lo, hi, weight / 3))
    edges = [(lo, hi) for lo, hi, _ in bands]
    pv, po = _band_power(vocal, fs, mask, edges), _band_power(other, fs, mask, edges)
    out = []
    for (lo, hi, weight), v, o in zip(bands, pv, po, strict=True):
        if v > 0 and o > 0:
            out.append(BandMasking(lo, hi, 10 * math.log10(o / v), weight))
    return out
