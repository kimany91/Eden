"""Measurements Eden bases its mix decisions on.

All values are measured on FL Studio's renders (the voice *with* its FL
effects), so Eden reacts to what the voice really sounds like after the
user's own chain, and does not correct what is already right.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.linalg import solve_toeplitz
from scipy.signal import freqz, welch

from eden.mix.dsp import band_levels_db, split_band
from eden.mix.loudness import block_loudness, integrated_loudness, loudness_of_blocks

ACTIVE_RANGE_DB = 35.0  # 1 ms frames this close to the loud parts count as "singing"
ANALYSIS_LOW_HZ, ANALYSIS_HIGH_HZ = 150.0, 8000.0


@dataclass
class Resonance:
    freq_hz: float
    excess_db: float


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
    dynamic_spread_db: float = 0.0  # P90 − P10 of the 400 ms loudness while singing
    crest_db: float = 0.0  # peak to RMS while singing
    detector_p70_db: float = -math.inf  # level used to place a compressor threshold
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


def spectral_envelope(sung: np.ndarray, fs: float, frame_s: float = 0.03, nfft: int = 2048
                      ) -> tuple[np.ndarray, np.ndarray]:
    """Average LPC envelope of the voice (dB): the shape of the sound, without the notes.

    Linear prediction follows the resonances of the voice and of the room,
    not the harmonics of the sung pitch; averaging over many syllables then
    flattens the moving vowel formants and keeps what never moves.
    """
    order = int(fs / 1000) + 4
    n = int(frame_s * fs)
    window = np.hanning(n)
    total = np.zeros(nfft)
    count = 0
    freqs = np.linspace(0, fs / 2, nfft, endpoint=False)
    for start in range(0, sung.size - n, n):
        frame = sung[start:start + n] * window
        r = np.correlate(frame, frame, "full")[n - 1:n + order]
        if r[0] < 1e-10:
            continue
        r[0] *= 1 + 1e-9
        try:
            a = solve_toeplitz(r[:order], -r[1:order + 1])
        except np.linalg.LinAlgError:
            continue
        _, h = freqz([1.0], np.concatenate([[1.0], a]), worN=nfft, fs=fs)
        env = 20 * np.log10(np.abs(h) + 1e-12)
        total += env - env.max()
        count += 1
    return freqs, (total / count if count else total)


def find_resonances(sung: np.ndarray, fs: float, min_excess_db: float = 4.5,
                    max_count: int = 3) -> list[Resonance]:
    """Fixed bumps in the voice's average envelope (room or microphone resonances).

    The threshold is strict on purpose: a missed resonance costs less than
    notching notes the artist wants (Auto-Tune holding the same notes can
    leave small bumps of its own).
    """
    if sung.size < 4 * fs:
        return []
    freqs, env = spectral_envelope(sung, fs)
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


def sibilance(x: np.ndarray, fs: float, level: np.ndarray, active: np.ndarray
              ) -> tuple[float, float, float]:
    """(vowel level, loud 's' minus vowels, share of 's') from 1 ms frames.

    A frame is an 's' when the band above 4.5 kHz carries most of its energy,
    a vowel when that band is far below. Piercing sibilants are 's' sounds
    nearly as loud as the vowels or louder.
    """
    high, _ = split_band(x, fs, 4500.0, None)
    hlevel, _ = band_levels_db(high, fs)
    n = min(hlevel.size, level.size)
    full, hi, act = level[:n], hlevel[:n], active[:n]
    s_frames = act & (hi - full > -3.0)
    vowels = act & (hi - full < -15.0)
    if not vowels.any():
        return -math.inf, -math.inf, 0.0
    vowel = float(np.percentile(full[vowels], 75))
    if not s_frames.any():
        return vowel, -math.inf, 0.0
    return vowel, float(np.percentile(full[s_frames], 90)) - vowel, float(s_frames.sum() / act.sum())


def measure_vocal(x: np.ndarray, fs: float) -> VocalMeasure:
    level, active, size = active_frames(x, fs)
    if not active.any():
        return VocalMeasure(-math.inf, 0.0, -math.inf, -math.inf, 0.0)
    sung = sung_samples(x, active, size)
    freqs, psd = _psd_db(sung, fs)
    total = _band_db(freqs, psd, 20, fs / 2)
    blocks = block_loudness(x, fs)
    lufs = integrated_loudness(x, fs)
    active_blocks = np.isfinite(blocks) & (blocks > lufs - 10)
    sung_blocks = blocks[active_blocks]

    vowel_level, sib_excess, sib_share = sibilance(x, fs, level, active)

    sung_level = level[active]
    rms_db = 10 * math.log10(np.mean(10 ** (sung_level / 10)))
    peak_db = 20 * math.log10(max(float(np.max(np.abs(x))), 1e-12))
    return VocalMeasure(
        loudness_lufs=lufs,
        active_share=float(active.mean()),
        low_energy_db=_band_db(freqs, psd, 20, 70) - total,
        low_120_db=_band_db(freqs, psd, 20, 120) - total,
        mud_db=_band_db(freqs, psd, 200, 500) - _band_db(freqs, psd, 1000, 4000),
        resonances=find_resonances(sung, fs),
        vowel_level_db=vowel_level,
        sibilant_excess_db=sib_excess,
        sibilant_share=sib_share,
        dynamic_spread_db=float(np.percentile(sung_blocks, 90) - np.percentile(sung_blocks, 10))
        if sung_blocks.size >= 4 else 0.0,
        crest_db=peak_db - rms_db,
        detector_p70_db=float(np.percentile(sung_level, 70)),
        active_blocks=active_blocks,
    )


def balance_against(vocal: VocalMeasure, other: np.ndarray, fs: float) -> float:
    """Voice loudness minus the loudness of ``other`` while the voice sounds (dB)."""
    other_lufs = loudness_of_blocks(other, fs, vocal.active_blocks)
    if not math.isfinite(other_lufs) or not math.isfinite(vocal.loudness_lufs):
        return math.inf
    return vocal.loudness_lufs - other_lufs


def presence_masking_db(vocal: np.ndarray, other: np.ndarray, fs: float, mask: np.ndarray) -> float:
    """How loud ``other`` is in the 1.5–4 kHz band compared with the voice, while it sings."""
    vb, _ = split_band(vocal, fs, 1500.0, 4000.0)
    ob, _ = split_band(other, fs, 1500.0, 4000.0)
    lv = loudness_of_blocks(vb, fs, mask)
    lo = loudness_of_blocks(ob, fs, mask)
    if not (math.isfinite(lv) and math.isfinite(lo)):
        return -math.inf
    return lo - lv
