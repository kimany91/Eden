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
   beat above ``MASKING_FROM_HZ``, over the moments the voice sounds: the
   band that masks words (an 808's sub hardly does);
3. a phrase whose beat is more than ``EXPOSED_DB`` under the median phrase's
   beat (a breakdown, a filter sweep, the beat cut for a punchline) is
   exposed: the voice already stands out there, it is left alone and not
   counted in the reference;
4. the reference is the median difference of the other phrases; a phrase
   further than ``TOLERANCE_DB`` from it gets the gain that brings it back,
   clamped to ±``MAX_RIDE_DB`` times the intensity. It is brought down only
   as far as the voice itself got louder than its median phrase: a beat that
   got quieter is never a reason to lower the voice;
5. each phrase keeps its gain through the rest that follows it (an FL echo
   tail stays at its phrase's level) and the next gain fades in during the
   end of that rest, never on a word.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import butter, sosfilt

from eden.mix import dsp
from eden.mix.loudness import k_weighting

MAX_RIDE_DB = 6.0  # a vocal rider's default range (±6 dB)
TOLERANCE_DB = 1.5  # phrases this close to the song's balance are left alone
MASKING_FROM_HZ = 200.0  # the beat is measured above this: the band that masks words
EXPOSED_DB = 6.0  # a phrase whose beat is this much under the median phrase's is never ridden
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
    gain_db: float
    exposed: bool  # the beat is more than EXPOSED_DB under its median phrase: left alone


@dataclass
class RideResult:
    phrases: list[Phrase]
    gain: np.ndarray  # per sample, linear
    reference_db: float = 0.0  # the median voice-minus-beat difference of the phrases not exposed

    @property
    def max_change_db(self) -> float:
        return max((abs(p.gain_db) for p in self.phrases), default=0.0)

    @property
    def moved(self) -> int:
        return sum(1 for p in self.phrases if abs(p.gain_db) >= 0.1)

    @property
    def exposed(self) -> int:
        return sum(1 for p in self.phrases if p.exposed)


def _k_power(x: np.ndarray, fs: float, size: int, above_hz: float | None = None) -> np.ndarray:
    """K-weighted power per frame of ``size`` samples (channels added, as BS.1770 does), with
    everything under ``above_hz`` removed first (4th-order high-pass) when it is given."""
    sos = k_weighting(fs)
    if above_hz:
        sos = np.vstack([sos, butter(4, above_hz, btype="highpass", fs=fs, output="sos")])
    weighted = sosfilt(sos, x if x.ndim == 2 else x[:, None], axis=0)
    power = weighted[:, 0] ** 2
    for c in range(1, weighted.shape[1]):
        power += weighted[:, c] ** 2
    n = power.size // size
    return power[: n * size].reshape(n, size).mean(axis=1)


def _db(power: list[float]) -> np.ndarray:
    """dB of each power, −inf for silence."""
    p = np.array(power, dtype=float)
    out = np.full(p.shape, -np.inf)
    np.log10(p, out=out, where=p > 0)
    return 10 * out


def phrase_levels(voice: np.ndarray, beat: np.ndarray, fs: float, tempo_bpm: float | None
                  ) -> tuple[list[tuple[int, int]], np.ndarray, np.ndarray, int]:
    """(phrases in 1 ms frames, K-weighted dB of the voice and of the beat above
    ``MASKING_FROM_HZ`` over each phrase's sung moments, −inf for silence, frame size)."""
    level, size = dsp.band_levels_db(voice, fs)
    if level.size == 0:
        return [], np.zeros(0), np.zeros(0), size
    active = level > max(-90.0, float(np.percentile(level, 95)) - 30.0)
    gap_s = felt_quarter(tempo_bpm) / 2 if tempo_bpm else 0.3  # an eighth of the felt pulse
    phrases = [(s, e) for s, e in phrases_of(active, int(gap_s / dsp.FRAME_S))
               if (e - s) * dsp.FRAME_S >= MIN_PHRASE_S]
    pv, pb = _k_power(voice, fs, size), _k_power(beat, fs, size, MASKING_FROM_HZ)
    n = min(pv.size, pb.size, active.size)
    v, b = [], []
    for s, e in phrases:
        on = active[s:min(e, n)]
        v.append(float(pv[s:min(e, n)][on].mean()) if on.any() else 0.0)
        b.append(float(pb[s:min(e, n)][on].mean()) if on.any() else 0.0)
    return phrases, _db(v), _db(b), size


def _differences(voice_db: np.ndarray, beat_db: np.ndarray) -> np.ndarray:
    """Voice minus beat per phrase, NaN where either is silent."""
    diffs = np.full(voice_db.shape, np.nan)
    both = np.isfinite(voice_db) & np.isfinite(beat_db)
    diffs[both] = voice_db[both] - beat_db[both]
    return diffs


def ride(voice: np.ndarray, beat: np.ndarray, fs: float, tempo_bpm: float | None, intensity: float
         ) -> RideResult:
    n = voice.shape[0]
    k = max(0.0, min(1.0, intensity))
    unity = RideResult([], np.ones(n))
    if k <= 0:
        return unity
    phrases, voice_db, beat_db, size = phrase_levels(voice, beat, fs, tempo_bpm)
    diffs = _differences(voice_db, beat_db)
    heard = np.isfinite(beat_db)
    if heard.sum() < 2:
        return unity
    exposed = ~heard | (beat_db < float(np.median(beat_db[heard])) - EXPOSED_DB)
    compared = np.isfinite(diffs) & ~exposed
    if compared.sum() < 2:
        return unity
    reference = float(np.median(diffs[compared]))
    voice_median = float(np.median(voice_db[np.isfinite(voice_db)]))
    frames = -(-n // size)
    gain_db = np.zeros(frames)
    fade = max(1, int(CROSSFADE_S / dsp.FRAME_S))
    result: list[Phrase] = []
    previous = 0.0
    for i, ((s, e), d, v) in enumerate(zip(phrases, diffs, voice_db, strict=True)):
        g = 0.0
        if compared[i] and abs(d - reference) > TOLERANCE_DB:
            move = reference - d
            if move < 0:  # down only as far as the voice itself got louder than its median phrase
                move = max(move, -max(0.0, v - voice_median))
            g = float(np.clip(move, -MAX_RIDE_DB, MAX_RIDE_DB)) * k
        result.append(Phrase(s * dsp.FRAME_S, e * dsp.FRAME_S, g, bool(exposed[i])))
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
