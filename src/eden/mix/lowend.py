"""Low end of a rap mix: the 808, the kick and what small speakers hear.

* 808 pitch: tracked note by note on the bass part (low-passed, decimated,
  normalised square difference function of McLeod & Wyvill with parabolic
  refinement); the frames of a glide are left out, so the pitches a slide
  passes through are not taken for notes; the notes are then compared with
  the song's scale and with equal temperament on the beat's own tuning;
* 808 notes evened out: the head of each note (where the tracker reads one,
  and where the same pitch is played again) is read on the bass groups
  alone, where no kick gets in the way; when the notes vary by more than
  4 dB from one to the next, a gentle compressor below 100 Hz brings the
  loudest ones closer (hearing is far less sensitive down there, so level
  differences sound bigger than they measure);
* kick / 808 collisions: how often the 808 is still sounding when a kick
  hits, and whether the 808 already dips after each kick (against its own
  decay); a duck below 100 Hz only, at most 3 dB, is added only when they
  collide and nothing ducks already — engineers disagree about ducking, so
  Eden stays conservative;
* harmonics for small speakers: when an 808 is close to a pure sine it
  vanishes on laptops and small speakers; harmonics 2–5 generated from the
  sub band only (the "missing fundamental" effect: the ear rebuilds the
  pitch from the 3rd to 5th harmonics) let its note through, at a level
  well under the fundamental.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from scipy.signal import butter, resample_poly, sosfiltfilt, welch

from eden.mix import dsp, stereo
from eden.mix.oversampling import shape_change
from eden.mix.tonality import NOTE_NAMES
from eden.mix.treatments import _moves

CROSSOVER_HZ = 100.0
SUB_BAND = (25.0, 80.0)
HARMONIC_BAND = (80.0, 400.0)
MAX_DUCK_DB = 3.0
# 808 notes evened out (choix d'Eden)
NOTE_STEP_DB = 3.0  # the same pitch played again: the low band rises this much (legato: drops)...
NOTE_STEP_MS = 30  # ...within this time (1 ms frames)
NOTE_STEADY_DB = 1.5  # a legato drop lies between two stretches that each hold within this over 80 ms
NOTE_HEAD_MS = 80  # a note's level: the top of its first 80 ms; one note per 80 ms at most
NOTE_LATE_MS = 200  # the pitch tracker places a note up to this long after its attack...
NOTE_EARLY_MS = 40  # ...or up to this long before it
NOTE_RANGE_DB = 30.0  # moves count within this of the loudest moment of the low band
EVEN_MAX_F0_HZ = 80.0  # higher notes lose part of their fundamental to the band split: not compared
EVEN_MIN_NOTES = 4
EVEN_SPREAD_DB = 4.0  # heads spread more than this (10th to 90th percentile): the notes are evened out
EVEN_P90_DB = 1.5  # what the compressor's curve takes from the 90th-percentile head at 100 %
EVEN_MAX_DB = 3.0  # its largest reduction at 100 %
EVEN_ATTACK_MS = 10.0
EVEN_RELEASE_MS = 150.0
EVEN_KNEE_DB = 6.0  # its soft knee


@dataclass
class BassNote:
    start_s: float
    end_s: float
    f0_hz: float
    tuning_cents: float = 0.0  # the beat's tuning: notes are named on its grid

    @property
    def midi(self) -> float:
        return 69 + 12 * math.log2(self.f0_hz / 440.0) - self.tuning_cents / 100

    @property
    def pitch_class(self) -> int:
        return int(round(self.midi)) % 12

    @property
    def cents_off(self) -> float:
        return (self.midi - round(self.midi)) * 100


@dataclass
class LowEndReport:
    notes: list[BassNote] = field(default_factory=list)
    root: int | None = None  # most played pitch class
    out_of_scale: list[str] = field(default_factory=list)  # note names outside the song's scale
    detune_cents: float | None = None  # median distance from the beat's semitone grid
    low_correlation: float = 1.0  # L/R correlation of the beat below the crossover
    kick_overlap: float = 0.0  # share of kick hits landing on a sounding 808
    existing_duck_db: float = 0.0  # how much the 808 already dips after a kick
    harmonics_db: float = math.nan  # 80–400 Hz relative to 25–80 Hz in the bass part
    actions: list[str] = field(default_factory=list)

    @property
    def root_name(self) -> str | None:
        return NOTE_NAMES[self.root] if self.root is not None else None


def _low_mono(x: np.ndarray, fs: float, cutoff: float = 200.0) -> tuple[np.ndarray, float]:
    """Mono low band decimated to about 4 kHz: enough for 25–150 Hz pitch tracking."""
    mono = x.mean(axis=1) if x.ndim == 2 else x
    low = sosfiltfilt(butter(4, cutoff, fs=fs, output="sos"), mono)
    factor = max(1, int(fs // 4000))
    return resample_poly(low, 1, factor), fs / factor


def track_bass(x: np.ndarray, fs: float, fmin: float = 25.0, fmax: float = 150.0,
               frame_s: float = 0.15, hop_s: float = 0.01, tuning_cents: float = 0.0) -> list[BassNote]:
    """Notes of the bass part: (start, end, f0), one per stretch held on the same semitone.

    Pitch per frame from the normalised square difference function (McLeod &
    Wyvill 2005): unlike a plain autocorrelation it does not lean towards
    short lags on a decaying note (a sharp bias), and its first strong peak
    avoids octave errors. Frames are grouped by semitone of the beat's grid;
    frames where the pitch is gliding are left out, so a glide from one note
    to another gives those two notes, not the semitones it passes through.
    """
    low, lfs = _low_mono(x, fs)
    n, hop = int(frame_s * lfs), int(hop_s * lfs)
    lag_min, lag_max = int(lfs / fmax), int(lfs / fmin) + 1
    if low.size < 2 * n or lag_max + 1 >= n:
        return []
    peak = float(np.max(np.abs(low)))
    if peak <= 0:
        return []
    frames = dsp.frame_matrix(low, n, hop)[: (low.size - n - 1) // hop + 1]
    r = dsp.autocorrelation(frames, lag_max + 1)
    sq = frames ** 2
    zero = np.zeros((frames.shape[0], 1))
    head = np.concatenate([zero, np.cumsum(sq, axis=1)[:, :lag_max + 1]], axis=1)  # energy of the first τ samples
    tail = np.concatenate([zero, np.cumsum(sq[:, ::-1], axis=1)[:, :lag_max + 1]], axis=1)  # of the last τ
    m = 2 * sq.sum(axis=1, keepdims=True) - head - tail  # Σ x_j² + x_{j+τ}² over the overlap
    nsdf = 2 * r / np.maximum(m, 1e-30)
    region = nsdf[:, lag_min:lag_max + 1]
    best = region.max(axis=1)
    # first peak reaching 90 % of the best one: the fundamental, not a multiple of its period
    first = np.argmax(region >= 0.9 * best[:, None], axis=1)
    idx = lag_min + first
    while True:  # climb to the local maximum of that peak
        rows = np.arange(idx.size)
        step = (idx + 1 <= lag_max) & (nsdf[rows, np.minimum(idx + 1, lag_max + 1)] > nsdf[rows, idx])
        if not step.any():
            break
        idx = idx + step
    rows = np.arange(idx.size)
    a, b, c = nsdf[rows, idx - 1], nsdf[rows, idx], nsdf[rows, np.minimum(idx + 1, lag_max + 1)]
    den = a - 2 * b + c
    shift = np.where(den != 0, 0.5 * (a - c) / np.where(den != 0, den, 1.0), 0.0)
    loud = sq.sum(axis=1) >= (peak * 10 ** (-40 / 20)) ** 2 * n
    voiced = loud & (b >= 0.8)
    f0 = np.where(voiced, lfs / (idx + shift), np.nan)
    semitone = np.where(voiced, np.round(69 + 12 * np.log2(np.where(voiced, f0, 440.0) / 440.0)
                                         - tuning_cents / 100), -1).astype(int)
    # a glide is not a note: frames whose pitch moves by more than 30 cents over 60 ms are left out
    cents = 1200 * np.log2(np.where(voiced, f0, 1.0))
    moving = np.zeros(voiced.size, dtype=bool)
    moving[3:-3] = voiced[6:] & voiced[:-6] & (np.abs(cents[6:] - cents[:-6]) > 30.0)
    semitone[moving & voiced] = -1
    step = hop / lfs  # the real hop (decimation makes it differ slightly from hop_s)
    centre = n / 2 / lfs  # a frame's pitch belongs to its middle
    notes: list[BassNote] = []
    start = 0
    for i in range(1, semitone.size + 1):
        if i == semitone.size or semitone[i] != semitone[start]:
            if semitone[start] >= 0 and i - start >= 5:  # at least 50 ms on the same semitone
                notes.append(BassNote(start * step + centre, i * step + centre,
                                      float(np.median(f0[start:i])), tuning_cents))
            start = i
    return notes


@dataclass
class NoteHead:
    """Where an 808 note starts and how loud its head is."""
    start_s: float
    level_db: float  # top of the note's first NOTE_HEAD_MS, its power averaged over one of its periods
    detector_db: float  # the same top as a compressor's detector reads it (5 ms smoothing)


@dataclass
class EvenNotes:
    """The compressor that evens out the 808's notes, computed once on all the bass groups
    together: the same gain goes on each group's band below ``CROSSOVER_HZ``."""
    heads: list[NoteHead]
    spread_db: float  # 10th to 90th percentile of the heads' levels
    p90_db: float  # 90th percentile of the heads as the compressor's detector reads them
    ratio: float
    threshold_db: float  # on the compressor's detector level
    gain_db: np.ndarray = field(repr=False)  # reduction per frame (≤ 0 dB)
    frame: int  # samples per frame


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """(first, end) of each run of True in ``mask``."""
    edges = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(edges == 1).tolist(), np.flatnonzero(edges == -1).tolist(), strict=True))


def _note_starts(ms: np.ndarray, frame_s: float, note: BassNote, floor_db: float
                 ) -> tuple[list[int], np.ndarray, int]:
    """The frames where ``note`` starts and where its pitch is played again, read on its power
    per 1 ms frame ``ms`` averaged over one of its periods (a sub's waveform does not ripple in
    it): (starts, that level in dB from the frame ``offset``, offset). Only moves that reach
    ``floor_db`` count (the filters' faint ringing before an attack does not).

    A note starts on its attack: the level climbs ``NOTE_STEP_DB`` over its lowest point of the
    ``NOTE_STEP_MS`` before (a note played again climbs back from the short dip between the two).
    The tracker places a note up to about 150 ms after its attack (an 808 whose pitch falls at
    the attack) and up to about 30 ms before it: the note starts on the last rise from
    ``NOTE_LATE_MS`` before to ``NOTE_EARLY_MS`` after where the tracker places it; without
    one, where the last fall of as much in that stretch ends (a quieter note played legato). A
    pitch change with neither (a slide) goes on with the note before: what it has then is that
    note's decay, not a head of its own. Inside the note, the same pitch played again rises as
    much; held legato at a lower level, it falls as much between two stretches that each hold
    within ``NOTE_STEADY_DB`` over ``NOTE_HEAD_MS`` (it starts where the fall ends), unless it
    rises again within those ``NOTE_HEAD_MS``."""
    period = max(1, int(round(1 / (note.f0_hz * frame_s))))
    first, last = int(note.start_s / frame_s), int(note.end_s / frame_s)
    offset = first - NOTE_LATE_MS - NOTE_STEP_MS - period  # the rise, and the 30 ms before it
    stop = min(last + NOTE_HEAD_MS + period, ms.size)  # every start is before ``last``: its head too
    power = ms[max(offset, 0):stop]
    if offset < 0:  # before the song: silence
        power = np.concatenate([np.zeros(-offset), power])
    level = 10 * np.log10(np.maximum(np.convolve(power, np.ones(period) / period, mode="same"), 1e-20))
    # how far each frame stands over the lowest of the NOTE_STEP_MS before it, and under the highest
    up, down = np.zeros(level.size), np.zeros(level.size)
    if level.size > NOTE_STEP_MS:
        span = sliding_window_view(level, NOTE_STEP_MS + 1)
        up[NOTE_STEP_MS:] = level[NOTE_STEP_MS:] - span.min(axis=1)
        down[NOTE_STEP_MS:] = level[NOTE_STEP_MS:] - span.max(axis=1)
    valid = NOTE_STEP_MS + period  # a step read from the averaging's edge is not a move
    loud = level >= floor_db
    rises = [offset + r for r, _ in _runs((up >= NOTE_STEP_DB) & loud) if r >= valid]
    drops = [(low, high) for low, high in _runs(down <= -NOTE_STEP_DB) if low >= valid and high < loud.size
             and loud[high]]

    def near(frames: list[int]) -> list[int]:
        return [f for f in frames if first - NOTE_LATE_MS <= f <= first + NOTE_EARLY_MS][-1:]

    starts = near(rises) or near([offset + high for _, high in drops])
    after = starts[0] if starts else first
    starts += [r for r in rises if after < r < last]
    for low, high in drops:
        before = level[max(low - NOTE_STEP_MS - NOTE_HEAD_MS, 0):max(low - NOTE_STEP_MS, 0)]
        held = level[high:high + NOTE_HEAD_MS]
        at = offset + high
        if (after < at < last and before.size == held.size == NOTE_HEAD_MS
                and np.ptp(before) <= NOTE_STEADY_DB and np.ptp(held) <= NOTE_STEADY_DB
                and not any(at <= r < at + NOTE_HEAD_MS for r in rises)):
            starts.append(at)
    return starts, level, offset


def note_heads(low: np.ndarray, fs: float, notes: list[BassNote]) -> list[NoteHead]:
    """The head of each note of ``notes`` (``track_bass``) whose pitch is under ``EVEN_MAX_F0_HZ``,
    and of each time the same pitch is played again, on ``low``, the bass below the crossover:
    the top of its first ``NOTE_HEAD_MS`` (see ``_note_starts``). One note per ``NOTE_HEAD_MS``
    at most: a start closer to the one before is in that one's head."""
    ms, size = dsp._frames(low, fs)
    if ms.size == 0:
        return []
    frame_s = size / fs  # a frame is a whole number of samples: 44 at 44.1 kHz, not quite 1 ms
    floor_db = float(_centred_db(ms).max()) - NOTE_RANGE_DB
    power, _ = dsp.detector_power(low, fs)
    detector = 10 * np.log10(np.maximum(power, 1e-20))
    found: list[tuple[int, float]] = []
    for n in notes:
        if n.f0_hz > EVEN_MAX_F0_HZ:
            continue
        starts, level, offset = _note_starts(ms, frame_s, n, floor_db)
        for at in starts:
            at = max(at, 0)  # a climb out of the silence before the song: the song's first frame
            if at + NOTE_HEAD_MS <= ms.size:
                found.append((at, float(level[at - offset:at - offset + NOTE_HEAD_MS].max())))
    heads: list[NoteHead] = []
    last = -math.inf
    for at, level_db in sorted(found):
        if at - last >= NOTE_HEAD_MS:
            heads.append(NoteHead(at * frame_s, level_db, float(detector[at:at + NOTE_HEAD_MS].max())))
            last = at
    return heads


def _over_for(reduction_db: float, ratio: float) -> float:
    """How far above its threshold a level gets ``reduction_db`` on the compressor's curve
    (``ratio``, soft knee of ``EVEN_KNEE_DB``: within half the knee of the threshold, the reduction
    is slope · (over + knee / 2)² / (2 · knee), as in ``dsp.compressor_gain_db``)."""
    slope = 1 - 1 / ratio
    if reduction_db / slope >= EVEN_KNEE_DB / 2:
        return reduction_db / slope
    return math.sqrt(2 * EVEN_KNEE_DB * reduction_db / slope) - EVEN_KNEE_DB / 2


def even_notes(bass: np.ndarray, fs: float, notes: list[BassNote], k: float) -> EvenNotes | None:
    """When the 808's notes (``notes``, tracked on ``bass``: all the bass groups together) vary by
    more than ``EVEN_SPREAD_DB`` from one to the next (10th to 90th percentile of their heads,
    at least ``EVEN_MIN_NOTES`` of them), a compressor on the band below ``CROSSOVER_HZ``:
    ratio 1 + ``k``, at most ``EVEN_MAX_DB`` · ``k``, its threshold set so its curve (soft knee
    included) takes ``EVEN_P90_DB`` · ``k`` from the 90th-percentile head as its detector reads
    it. None when they do not vary that much, or when its reduction would not move
    (``treatments._moves``)."""
    if k <= 0 or not notes:
        return None
    low, _ = dsp.split_band(bass, fs, None, CROSSOVER_HZ)
    heads = note_heads(low, fs, notes)
    if len(heads) < EVEN_MIN_NOTES:
        return None
    levels = np.array([h.level_db for h in heads])
    spread = float(np.percentile(levels, 90) - np.percentile(levels, 10))
    if spread <= EVEN_SPREAD_DB:
        return None
    ratio = 1 + k
    p90 = float(np.percentile([h.detector_db for h in heads], 90))
    threshold = p90 - _over_for(EVEN_P90_DB * k, ratio)
    gain_db, frame = dsp.compressor_gain_db(low, fs, threshold, ratio, attack_ms=EVEN_ATTACK_MS,
                                            release_ms=EVEN_RELEASE_MS, knee_db=EVEN_KNEE_DB,
                                            max_reduction_db=EVEN_MAX_DB * k)
    if not _moves(gain_db, low, fs):
        return None
    return EvenNotes(heads, spread, p90, ratio, threshold, gain_db, frame)


def apply_low_gain(x: np.ndarray, fs: float, even: EvenNotes) -> np.ndarray:
    """``even``'s gain on the band of ``x`` below the crossover (zero-phase split, exact: above
    it, ``x`` is untouched; the split is linear, so on each group it is the gain on their sum)."""
    low, high = dsp.split_band(x, fs, None, CROSSOVER_HZ)
    return dsp._apply_gain(low, dsp._to_samples(even.gain_db, even.frame, low.shape[0])) + high


def _low_power(x: np.ndarray, fs: float, cutoff: float) -> np.ndarray:
    """Power of the band below ``cutoff`` (zero-phase filter) per 1 ms frame."""
    low = sosfiltfilt(butter(4, cutoff, fs=fs, output="sos"), x, axis=0)
    return dsp._frames(low, fs)[0]


def _centred_db(ms: np.ndarray) -> np.ndarray:
    """Power per 1 ms frame averaged over the 20 ms around each frame (one sub-bass cycle), in dB."""
    return 10 * np.log10(np.maximum(np.convolve(ms, np.ones(20) / 20, mode="same"), 1e-20))


def _low_envelope_db(x: np.ndarray, fs: float, cutoff: float) -> np.ndarray:
    """Level of the band below ``cutoff`` per 1 ms frame, averaged over 20 ms (one sub-bass cycle)."""
    ms = _low_power(x, fs, cutoff)
    return _centred_db(ms) if ms.size >= 20 else np.zeros(0)


def _onsets(x: np.ndarray, fs: float, low_hz: float = 150.0) -> np.ndarray:
    """Kick hits: where the drums' low band rises by 4 dB within 20 ms up to within 12 dB of
    its loudest hits (ghost kicks, and kicks landing on the previous kick's tail), at least
    60 ms apart (double kicks too).

    The rise is read on the centred 20 ms average, which already climbs up to 10 ms before
    the kick: each hit is then set on the kick's onset, the first 1 ms frame from 10 ms
    before to 10 ms after that stands 4 dB above the 20 ms before it and within 10 dB of
    the hit's level (the filter's faint ringing before the attack does not count)."""
    ms = _low_power(x, fs, low_hz)
    if ms.size < 30:
        return np.zeros(0, dtype=int)
    level = _centred_db(ms)
    loud = float(np.percentile(level, 99)) - 12.0
    rise = level[20:] - level[:-20]
    before = np.convolve(ms, np.ones(20) / 20)[:ms.size]  # mean of each frame and the 19 before it
    hits = []
    last = -1000
    for i in np.flatnonzero((rise > 4.0) & (level[20:] > loud)):
        if i + 20 - last >= 60:
            last = i + 20
            span = np.arange(max(last - 10, 1), min(last + 11, ms.size))
            hit = ms[last - 10:last + 30].mean()
            onset = span[(ms[span] > 10 ** 0.4 * before[span - 1]) & (ms[span] > 0.1 * hit)]
            hits.append(int(onset[0]) if onset.size else last)
    return np.array(hits, dtype=int)


def kick_808_interaction(bass: np.ndarray, drums: np.ndarray, fs: float) -> tuple[float, float, np.ndarray]:
    """(share of kicks landing on a sounding 808, 808 dip after kicks in dB, kick onset frames).

    The dip is measured against the 808's own decay, extrapolated from the
    35 ms before the kick: a note that simply fades is not an existing duck.
    """
    hits = _onsets(drums, fs)
    if hits.size == 0:
        return 0.0, 0.0, hits
    level = _low_envelope_db(bass, fs, CROSSOVER_HZ)
    floor = float(np.percentile(level, 95)) - 30.0
    overlap, dips = [], []
    after = np.arange(60)
    for h in hits:
        if h < 60 or h + 60 >= level.size:
            continue
        before = level[h - 25]  # just before the kick (the envelope is averaged over 20 ms)
        sounding = before > floor
        overlap.append(sounding)
        if sounding and level[h + 60] > floor:  # the note goes on: any dip is a duck, not its end
            slope = min(0.0, (level[h - 25] - level[h - 60]) / 35)  # dB per ms, decay only
            expected = before + slope * (after + 25)
            dips.append(float(np.max(expected - level[h:h + 60])))
    return (float(np.mean(overlap)) if overlap else 0.0,
            float(np.median(dips)) if dips else 0.0, hits)


def duck_low_band(bass: np.ndarray, fs: float, hits: np.ndarray, depth_db: float,
                  hold_ms: float = 30.0, release_ms: float = 100.0, ramp_ms: float = 5.0) -> np.ndarray:
    """Dip the band below the crossover by ``depth_db`` at each kick hit.

    The dip ramps in over ``ramp_ms`` (raised cosine) and is fully down when
    the kick starts: a faster move would cut a 40–60 Hz cycle mid-way and
    click. The band split is zero-phase and exact, so outside the dips the
    808 comes out bit-exact.
    """
    if depth_db <= 0 or hits.size == 0:
        return bass
    low, high = dsp.split_band(bass, fs, None, CROSSOVER_HZ)
    frames = low.shape[0] // max(1, int(fs / 1000)) + 1
    gain_db = np.zeros(frames)
    ramp = int(ramp_ms)
    shape = -depth_db * 0.5 * (1 - np.cos(np.pi * np.arange(1, ramp + 1) / ramp))
    tail = np.arange(1, int(release_ms) + 1)
    release = -depth_db * np.exp(-tail / (release_ms / 3))
    for h in hits:
        for start, curve in ((h - ramp, shape), (h, np.full(int(hold_ms), -depth_db)),
                             (h + int(hold_ms), release)):
            lo, hi = max(0, start), min(frames, start + curve.size)
            if hi > lo:
                gain_db[lo:hi] = np.minimum(gain_db[lo:hi], curve[lo - start:hi - start])
    gain = dsp._to_samples(gain_db, int(fs / 1000), low.shape[0])
    return dsp._apply_gain(low, gain) + high


def _around(freqs: np.ndarray, psd: np.ndarray, f: float) -> float:
    sel = (freqs >= f * 0.94) & (freqs <= f * 1.06)
    return float(np.sum(psd[sel])) if sel.any() else 0.0


def harmonics_db(bass: np.ndarray, fs: float, notes: list[BassNote]) -> float:
    """Energy of harmonics 2–5 relative to the fundamental, median over the 808's notes (dB)."""
    mono = bass.mean(axis=1) if bass.ndim == 2 else bass
    values = []
    for n in notes:
        seg = mono[int(n.start_s * fs):int(n.end_s * fs)]
        if seg.size < 0.2 * fs:
            continue
        freqs, psd = welch(seg, fs=fs, nperseg=min(1 << 15, seg.size))
        fund = _around(freqs, psd, n.f0_hz)
        harm = sum(_around(freqs, psd, h * n.f0_hz) for h in (2, 3, 4, 5))
        if fund > 0:
            values.append(10 * math.log10(harm / fund) if harm > 0 else -120.0)
    return float(np.median(values)) if values else math.nan


def _harmonic_shaper(u: np.ndarray) -> np.ndarray:
    """A full-wave rectifier (even harmonics) and a hard tanh (odd ones) together: harmonics
    2 to 5 at comparable levels, the region where the ear rebuilds a missing fundamental."""
    return u + 0.5 * np.abs(u) + 0.5 * (np.tanh(6 * u) / math.tanh(6) - u)


def add_harmonics(bass: np.ndarray, fs: float, target_db: float = -14.0, k: float = 1.0) -> np.ndarray:
    """Add harmonics 2–5 generated from the sub band (80–400 Hz), ``target_db`` under the sub."""
    if k <= 0:
        return bass
    sub, _ = dsp.split_band(bass, fs, None, 120.0)
    # each note is shaped at its own level: the envelope (30 ms RMS) brings every note to the same
    # drive, so quiet notes and decaying tails get the same harmonic colour as the loudest one
    size = max(1, int(0.03 * fs))
    power = np.convolve((sub ** 2).mean(axis=1) if sub.ndim == 2 else sub ** 2, np.ones(size) / size, mode="same")
    envelope = np.sqrt(np.maximum(power, power.max() * 1e-6)) * math.sqrt(2)
    if envelope.max() <= 0:
        return bass
    env = envelope[:, None] if sub.ndim == 2 else envelope
    shaped = shape_change(sub / env, fs, 4, _harmonic_shaper) * env
    # the shaper also returns a scaled copy of its input (its slope at zero is not 1): take it out,
    # 100 ms at a time, so this step adds harmonics and never raises the fundamental
    block = max(1, int(0.1 * fs))
    for start in range(0, sub.shape[0], block):
        a, b = sub[start:start + block], shaped[start:start + block]
        energy = float(np.sum(a * a))
        if energy > 0:
            b -= a * (float(np.sum(a * b)) / energy)
    band = sosfiltfilt(butter(2, HARMONIC_BAND, btype="bandpass", fs=fs, output="sos"), shaped, axis=0)
    e_sub = float(np.mean(sub ** 2))
    e_band = float(np.mean(band ** 2))
    if e_band <= 0:
        return bass
    gain = math.sqrt(e_sub * 10 ** (target_db / 10) / e_band)
    return bass + band * gain * k


def analyse(bass: np.ndarray | None, drums: np.ndarray | None, beat: np.ndarray, fs: float,
            scale: set[int] | None, tuning_cents: float = 0.0) -> LowEndReport:
    report = LowEndReport()
    report.low_correlation = stereo.low_band_correlation(beat, fs, CROSSOVER_HZ)
    if bass is not None:
        report.notes = track_bass(bass, fs, tuning_cents=tuning_cents)
        report.harmonics_db = harmonics_db(bass, fs, report.notes)
        if report.notes:
            weights: dict[int, float] = {}
            for n in report.notes:
                weights[n.pitch_class] = weights.get(n.pitch_class, 0.0) + (n.end_s - n.start_s)
            report.root = max(weights, key=weights.get)
            report.detune_cents = float(np.median([abs(n.cents_off) for n in report.notes]))
            if scale:
                minimum = max(0.5, 0.03 * sum(weights.values()))  # seconds: not a passing note
                outside = {n.pitch_class for n in report.notes
                           if n.pitch_class not in scale and weights[n.pitch_class] >= minimum}
                report.out_of_scale = [NOTE_NAMES[pc] for pc in sorted(outside)]
        if drums is not None:
            report.kick_overlap, report.existing_duck_db, _ = kick_808_interaction(bass, drums, fs)
    return report
