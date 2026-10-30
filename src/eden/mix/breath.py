"""Breaths found and brought down, before anything raises them.

What a mix engineer does first on a rap vocal: cut or ride down the breaths, because every
compressor after that point raises them (the dedicated tools — Waves DeBreath, iZotope Breath
Control, Vocal Rider's breath detection — exist for exactly this). A breath is told from a word
the way those tools describe it: it sits in a rest between phrases, it is quieter than the sung
voice, and it is noise (no harmonic low band, energy spread high), where a vowel is voiced.
Detected breaths are not cut dead (a vocal with no breath at all sounds edited): they are brought
down to ``BREATH_UNDER_DB`` under the sung voice, like the Target mode of iZotope's Breath
Control, which reduces loud breaths and leaves soft ones alone.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from eden.mix import dsp
from eden.mix.riding import phrases_of

VOICED_BAND_HZ = (120.0, 3500.0)  # where vowels live: phrases are read there, breaths hardly reach it
NOISE_BAND_HZ = (2000.0, 9000.0)  # where breath noise lives
PHRASE_UNDER_P95_DB = 25.0  # a frame sings when its voiced band is within this of the loud frames
PHRASE_JOIN_S = 0.15  # rests shorter than this stay inside a phrase (a 16th at most tempos)
MIN_PHRASE_S = 0.25
EDGE_S = 0.06  # a breath keeps this distance from the phrases: word onsets and tails are never touched
MIN_BREATH_S = 0.08
MAX_BREATH_S = 1.2
NOISY_DB = -6.0  # a segment is noise when its noise band comes within this of its voiced band
BREATH_UNDER_DB = 22.0  # where breaths are sent: under the sung voice (iZotope's Target mode idea)
MAX_REDUCTION_DB = 15.0
FADE_S = 0.02


@dataclass
class BreathResult:
    gain_db: np.ndarray  # per 1 ms frame
    size: int  # samples per frame
    count: int  # breaths brought down
    deepest_db: float  # the largest reduction


def sung_activity(x: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray, int]:
    """(1 ms frames that sing, voiced-band level of every frame, frame size): activity is read on the
    voiced band only, so breaths, headphone bleed and effect tails do not pass for phrases."""
    if x.shape[0] < int(0.2 * fs):  # shorter than any phrase: nothing sings (and too short to filter)
        return np.zeros(0, dtype=bool), np.zeros(0), max(1, int(round(dsp.FRAME_S * fs)))
    voiced, _ = dsp.split_band(x, fs, VOICED_BAND_HZ[0], VOICED_BAND_HZ[1])
    level, size = dsp.band_levels_db(voiced, fs)
    if level.size == 0:
        return np.zeros(0, dtype=bool), level, size
    loud = level[level > -90.0]
    threshold = float(np.percentile(loud, 95)) - PHRASE_UNDER_P95_DB if loud.size else 0.0
    sung = np.zeros(level.size, dtype=bool)
    for s, e in phrases_of(level > threshold, int(PHRASE_JOIN_S / dsp.FRAME_S)):
        if (e - s) * dsp.FRAME_S >= MIN_PHRASE_S:
            sung[s:e] = True
    return sung, level, size


def find_breaths(x: np.ndarray, fs: float, max_reduction_db: float = MAX_REDUCTION_DB) -> BreathResult:
    """Where the breaths are and the gain that brings each one under the sung voice."""
    sung, voiced_level, size = sung_activity(x, fs)
    gain_db = np.zeros(voiced_level.size)
    empty = BreathResult(gain_db, size, 0, 0.0)
    if not sung.any() or sung.all():
        return empty
    level, _ = dsp.band_levels_db(x, fs)
    noise, _ = dsp.split_band(x, fs, NOISE_BAND_HZ[0], NOISE_BAND_HZ[1])
    noise_level, _ = dsp.band_levels_db(noise, fs)
    n = min(level.size, noise_level.size, voiced_level.size)
    sung_db = float(np.percentile(level[:n][sung[:n]], 95))
    floor = sung_db - 60.0
    edge = int(EDGE_S / dsp.FRAME_S)
    away = sung.copy()  # frames within EDGE_S of a phrase are left with it
    for s, e in phrases_of(sung, 1):
        away[max(0, s - edge):min(away.size, e + edge)] = True
    candidates = ~away[:n] & (level[:n] > floor)
    count, deepest = 0, 0.0
    for s, e in phrases_of(candidates, int(0.03 / dsp.FRAME_S)):
        seconds = (e - s) * dsp.FRAME_S
        if not MIN_BREATH_S <= seconds <= MAX_BREATH_S:
            continue
        seg_level = level[s:e]
        heard = seg_level > floor
        if not heard.any():
            continue
        # noise, not a hummed note or a word: its noise band comes up to its voiced band
        if float(np.median(noise_level[s:e][heard] - voiced_level[s:e][heard])) < NOISY_DB:
            continue
        peak = float(np.percentile(seg_level[heard], 95))
        reduction = min(max_reduction_db, max(0.0, peak - (sung_db - BREATH_UNDER_DB)))
        if reduction < 1.0:
            continue  # a soft breath is left alone
        gain_db[s:e] = -reduction
        count += 1
        deepest = max(deepest, reduction)
    if not count:
        return empty
    fade = max(1, int(FADE_S / dsp.FRAME_S))
    gain_db = np.convolve(gain_db, np.ones(fade) / fade, mode="same")
    return BreathResult(gain_db, size, count, deepest)
