"""Vocal riding: keep the lead at a steady level above a changing beat.

A mix engineer rides the vocal fader phrase by phrase (or uses a vocal
rider): the controlled variable is the loudness of the voice relative to
the beat while the voice sounds, not the voice's own level. The static
balance has already put the voice at its place; riding only evens out the
phrases around it:

1. phrases are found on 1 ms frames: sound separated by rests of at least
   an eighth note of the felt pulse (rap rests are mostly one 16th note,
   ~180 ms, so shorter ones stay inside a phrase);
2. for each phrase, the K-weighted loudness of the voice minus that of the
   beat, over the moments the voice sounds;
3. the reference is the song's median difference; a phrase further than
   ``TOLERANCE_DB`` from it gets the gain that brings it back, clamped to
   ±``MAX_RIDE_DB`` times the intensity;
4. each phrase keeps its gain through the rest that follows it (an FL echo
   tail stays at its phrase's level) and the next gain fades in during the
   end of that rest, never on a word.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import sosfilt

from eden.mix import dsp
from eden.mix.loudness import k_weighting

MAX_RIDE_DB = 6.0  # a vocal rider's default range (±6 dB)
TOLERANCE_DB = 1.5  # phrases this close to the song's balance are left alone
CROSSFADE_S = 0.12  # fades sit in the rests, which are mostly one 16th note (~180 ms)
MIN_PHRASE_S = 0.3
FELT_BPM = (65.0, 135.0)  # rap's felt pulse: 79–124 BPM in MCFlow (10th–90th percentile)


def felt_quarter(tempo_bpm: float) -> float:
    """Quarter-note length (s) of the felt pulse: trap written at 140 BPM is felt at 70."""
    bpm = tempo_bpm
    while bpm > FELT_BPM[1]:
        bpm /= 2
    while bpm < FELT_BPM[0]:
        bpm *= 2
    return 60.0 / bpm


def phrases_of(active: np.ndarray, gap_frames: int) -> list[tuple[int, int]]:
    """[start, end) ranges of activity, joined when the gap between them is shorter than ``gap_frames``."""
    runs: list[tuple[int, int]] = []
    start = None
    for i, on in enumerate(active):
        if on and start is None:
            start = i
        elif not on and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, active.size))
    joined: list[tuple[int, int]] = []
    for s, e in runs:
        if joined and s - joined[-1][1] < gap_frames:
            joined[-1] = (joined[-1][0], e)
        else:
            joined.append((s, e))
    return joined


@dataclass
class Phrase:
    start_s: float
    end_s: float
    difference_db: float  # voice minus beat over the phrase
    gain_db: float


@dataclass
class RideResult:
    phrases: list[Phrase]
    gain: np.ndarray  # per sample, linear
    reference_db: float = 0.0  # the song's median voice-minus-beat difference

    @property
    def max_change_db(self) -> float:
        return max((abs(p.gain_db) for p in self.phrases), default=0.0)

    @property
    def moved(self) -> int:
        return sum(1 for p in self.phrases if abs(p.gain_db) >= 0.1)


def _k_power(x: np.ndarray, fs: float, size: int) -> np.ndarray:
    """K-weighted power per frame of ``size`` samples (channels added, as BS.1770 does)."""
    weighted = sosfilt(k_weighting(fs), x if x.ndim == 2 else x[:, None], axis=0)
    power = weighted[:, 0] ** 2
    for c in range(1, weighted.shape[1]):
        power += weighted[:, c] ** 2
    n = power.size // size
    return power[: n * size].reshape(n, size).mean(axis=1)


def phrase_differences(voice: np.ndarray, beat: np.ndarray, fs: float, tempo_bpm: float | None
                       ) -> tuple[list[tuple[int, int]], np.ndarray, int]:
    """(phrases in 1 ms frames, voice-minus-beat dB per phrase, frame size in samples)."""
    level, size = dsp.band_levels_db(voice, fs)
    if level.size == 0:
        return [], np.zeros(0), size
    active = level > max(-60.0, float(np.percentile(level, 95)) - 30.0)
    gap_s = felt_quarter(tempo_bpm) / 2 if tempo_bpm else 0.3  # an eighth of the felt pulse
    phrases = [(s, e) for s, e in phrases_of(active, int(gap_s / dsp.FRAME_S))
               if (e - s) * dsp.FRAME_S >= MIN_PHRASE_S]
    pv, pb = _k_power(voice, fs, size), _k_power(beat, fs, size)
    n = min(pv.size, pb.size, active.size)
    diffs = []
    for s, e in phrases:
        on = active[s:min(e, n)]
        v = float(pv[s:min(e, n)][on].mean()) if on.any() else 0.0
        b = float(pb[s:min(e, n)][on].mean()) if on.any() else 0.0
        diffs.append(10 * np.log10(v / b) if v > 0 and b > 0 else np.nan)
    return phrases, np.array(diffs), size


def ride(voice: np.ndarray, beat: np.ndarray, fs: float, tempo_bpm: float | None, intensity: float
         ) -> RideResult:
    n = voice.shape[0]
    k = max(0.0, min(1.0, intensity))
    unity = RideResult([], np.ones(n))
    if k <= 0:
        return unity
    phrases, diffs, size = phrase_differences(voice, beat, fs, tempo_bpm)
    valid = np.isfinite(diffs)
    if valid.sum() < 2:
        return unity
    reference = float(np.median(diffs[valid]))
    frames = -(-n // size)
    gain_db = np.zeros(frames)
    fade = max(1, int(CROSSFADE_S / dsp.FRAME_S))
    result: list[Phrase] = []
    previous = 0.0
    for i, ((s, e), d) in enumerate(zip(phrases, diffs, strict=True)):
        g = 0.0
        if np.isfinite(d) and abs(d - reference) > TOLERANCE_DB:
            g = float(np.clip(reference - d, -MAX_RIDE_DB, MAX_RIDE_DB)) * k
        result.append(Phrase(s * dsp.FRAME_S, e * dsp.FRAME_S, float(d), g))
        # the new gain fades in at the end of the previous phrase's rest, then holds through
        # this phrase and its own rest, up to the fade before the next phrase
        start = max(s - fade, phrases[i - 1][1]) if i else 0
        end = max(phrases[i + 1][0] - fade, e) if i + 1 < len(phrases) else frames
        if s > start:
            gain_db[start:s] = np.linspace(previous, g, s - start + 1)[1:]
        gain_db[s:end] = g
        previous = g
    return RideResult(result, dsp._to_samples(gain_db, size, n), reference)


def apply_ride(x: np.ndarray, result: RideResult) -> np.ndarray:
    gain = result.gain[: x.shape[0]]
    return x * (gain[:, None] if x.ndim == 2 else gain)


def steadiness_db(voice: np.ndarray, beat: np.ndarray, fs: float, tempo_bpm: float | None = None) -> float:
    """Spread (P90 − P10) of the phrase-by-phrase voice-minus-beat difference."""
    _, diffs, _ = phrase_differences(voice, beat, fs, tempo_bpm)
    d = diffs[np.isfinite(diffs)]
    return float(np.percentile(d, 90) - np.percentile(d, 10)) if d.size >= 2 else 0.0
