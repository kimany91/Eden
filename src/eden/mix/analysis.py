"""Measurements Eden bases its mix decisions on.

All values are measured on FL Studio's renders: the voice with its whole FL
chain or, when FL also rendered it without its reverbs and delays, that dry
render (the FL effects are put back untouched afterwards). Eden reacts to
what the voice really sounds like after the user's own chain, and does not
correct what is already right.

Levels and spectra are taken channel by channel and their powers averaged,
like the loudness meter does: a voice widened in FL (one side delayed,
opposite polarity) is measured as it is heard, not through a mono fold that
would comb-filter it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy import fft
from scipy.signal import butter, get_window, resample_poly, sosfiltfilt, welch

from eden.mix.dsp import autocorrelation, band_levels_db, frame_matrix, split_band
from eden.mix.loudness import block_loudness, gated_loudness, loudness_of_blocks

ACTIVE_RANGE_DB = 35.0  # 1 ms frames this close to the loud parts count as "singing"
SILENCE_DB = -90.0  # quieter 1 ms frames are digital silence or dither, however low the voice was rendered
ANALYSIS_LOW_HZ, ANALYSIS_HIGH_HZ = 150.0, 8000.0
HARMONIC_HIGH_HZ = 2000.0  # resonances below are read on the sung harmonics, above on the LPC envelope
RESONANCE_MIN_DB = 4.5  # how far a resonance must stick out (strict: a missed one costs less than a wrong cut)
# lift of the harmonics over 1/3 octave that makes a low-mid bump (Eden's choice): +6 dB bumps at 200–400 Hz
# read 2.94 dB or more on the test voices (seeds 1–20); clean voices show no bump on two notes at all
LOW_MID_MIN_DB = 2.5
# a note shows a low-mid bump when its harmonics there stand above their neighbours' line in this share of
# the cases (Eden's choice): a fixed bump lifts them every time (two notes or more at 100 % on the test voices),
# the vowels' first formant only when the vowel puts it there (clean test voices, where every note pooled reads
# 2.5 dB or more with mud over 6 dB: one note 85 % at most, a second one 74 %)
LOW_MID_STEADY_SHARE = 0.9
FREQUENT_NOTE_SHARE = 0.3  # a semitone holding this share of the pitched frames is a note the voice dwells on
LOW_SPECTRUM_HZ = 100.0  # the high-pass is decided on the spectrum below this (half its highest cut is 80 Hz)
REST_SPECTRUM_HZ = 160.0  # ... and on the rests' spectrum below this (its highest cut, back vocals)
REST_WINDOW_S = 0.25  # rests are read on stretches at least this long, their spectrum 4 Hz apart (Eden's choice)
MAX_REST_WINDOWS = 2000  # evenly spread over the song: plenty for an average


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
    mud_db: float  # 200–500 Hz relative to 1–4 kHz
    resonances: list[Resonance] = field(default_factory=list)
    sibilant_excess_db: float = -math.inf  # loud 's' in the de-esser's band relative to the vowels
    sibilant_share: float = 0.0  # share of sung time where 's' sounds dominate
    dynamic_spread_db: float = 0.0  # P90 − P10 of the 400 ms loudness inside phrases (rests excluded)
    crest_db: float = 0.0  # peak to RMS while singing
    sung_p70_db: float = -math.inf  # typical level of the sung moments (1 ms frames)
    lowest_f0_hz: float | None = None  # lowest sustained pitch of the voice
    sibilant_peak_hz: float | None = None  # where the 's' sounds have their energy
    low_mid_hz: float = 300.0  # centre of the low-mid build-up (proximity, boxiness)
    low_mid_excess_db: float = 0.0  # how much the harmonics there stick out of their neighbours' line
    low_mid_notes: int = 0  # how many sung notes show that bump on their own (see ``low_mid_buildup``)
    air_db: float = -math.inf  # energy above 8 kHz relative to 2–5 kHz, on vowels only
    low_hz: np.ndarray = field(default_factory=lambda: np.zeros(0), repr=False)  # about 1 Hz apart
    low_share: np.ndarray = field(default_factory=lambda: np.zeros(0), repr=False)  # of the energy, per low_hz
    rest_low_hz: np.ndarray = field(default_factory=lambda: np.zeros(0), repr=False)  # 4 Hz apart
    # power in the rests between phrases relative to the sung voice's power, per rest_low_hz
    rest_low_share: np.ndarray = field(default_factory=lambda: np.zeros(0), repr=False)
    active_blocks: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool), repr=False)

    def energy_below_db(self, hz: float) -> float:
        """Energy of the voice below ``hz`` (at most LOW_SPECTRUM_HZ) relative to the whole voice (dB)."""
        return _share_db(self.low_share[self.low_hz < hz])

    def rest_energy_below_db(self, hz: float) -> float:
        """Power below ``hz`` (at most REST_SPECTRUM_HZ) in the rests between phrases, relative to the
        power of the sung voice (dB; −inf when the voice never rests REST_WINDOW_S, see
        ``_rest_low_spectrum``)."""
        return _share_db(self.rest_low_share[self.rest_low_hz < hz])


def _share_db(shares: np.ndarray) -> float:
    total = float(shares.sum())
    return 10 * math.log10(total) if total > 0 else -math.inf


def _channels(x: np.ndarray) -> np.ndarray:
    return x if x.ndim == 2 else x[:, None]


def active_frames(x: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray, int]:
    """Level of each 1 ms frame (dB, channels' powers averaged), which frames are sung, frame size.

    Sung = within ACTIVE_RANGE_DB of the loud parts; the absolute floor only
    excludes digital silence, so the same voice rendered quieter is measured
    the same way.
    """
    level, size = band_levels_db(x, fs)
    if level.size == 0:
        return level, np.zeros(0, dtype=bool), size
    top = np.percentile(level, 95)
    return level, level > max(SILENCE_DB, top - ACTIVE_RANGE_DB), size


def sung_samples(x: np.ndarray, active: np.ndarray, size: int) -> np.ndarray:
    """The voice with its silences removed (samples × channels)."""
    sig = _channels(x)
    mask = np.repeat(active, size)
    sung = sig[: mask.size][mask]
    return sung if sung.shape[0] >= 4096 else sig


def _psd_db(sung: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
    """Welch spectrum (dB) of every channel, their powers averaged (one channel at a time: Welch's
    overlapping frames take several times the signal's memory)."""
    nper = min(8192, max(256, 1 << int(math.log2(max(sung.shape[0], 256)))), max(sung.shape[0], 1))
    freqs, psd = welch(sung[:, 0], fs=fs, nperseg=nper)
    for c in range(1, sung.shape[1]):
        psd = psd + welch(sung[:, c], fs=fs, nperseg=nper)[1]
    return freqs, 10 * np.log10(np.maximum(psd / sung.shape[1], 1e-30))


def _band_db(freqs: np.ndarray, psd_db: np.ndarray, lo: float, hi: float) -> float:
    sel = (freqs >= lo) & (freqs < hi)
    if not sel.any():
        return -math.inf
    return 10 * math.log10(np.sum(10 ** (psd_db[sel] / 10)) + 1e-30)


def _low_spectrum(sung: np.ndarray, fs: float, sung_power: float) -> tuple[np.ndarray, np.ndarray]:
    """(frequencies about 1 Hz apart below LOW_SPECTRUM_HZ, share of the voice's energy at each).

    Fine enough that the energy under a high-pass set just below the lowest
    note (0.9 × its pitch) does not include that note.
    """
    down = max(1, int(fs // 1000))
    low = resample_poly(sung, 1, down, axis=0)
    rate = fs / down
    nper = min(1 << int(math.ceil(math.log2(rate))), low.shape[0])
    freqs, psd = welch(low, fs=rate, nperseg=nper, axis=0)
    keep = freqs < LOW_SPECTRUM_HZ
    return freqs[keep], psd.mean(axis=1)[keep] * (rate / nper) / sung_power


def _rest_low_spectrum(x: np.ndarray, fs: float, sung_power: float) -> tuple[np.ndarray, np.ndarray]:
    """(frequencies 4 Hz apart below REST_SPECTRUM_HZ, power at each in the rests between phrases
    relative to the power of the sung voice).

    Rests are where the voice's own band (LOW_SPECTRUM_HZ to 500 Hz, averaged
    over 10 ms) stays ACTIVE_RANGE_DB under its loud parts, digital silence
    excluded: the voice is silent there, so what sounds under a high-pass is
    noise (rumble, handling), and a loud rumble cannot make a rest pass for
    singing. They are read on the voice decimated to about 1 kHz, in windows
    of REST_WINDOW_S lying wholly in a rest (every rest at least that long
    has some; at most MAX_REST_WINDOWS, evenly spread), each with its mean
    removed and a Hann window: never pasted to the next rest, which would add
    the jumps between them. Empty when the voice never rests that long.
    """
    down = max(1, int(fs // 1000))
    rate = fs / down
    n = int(round(REST_WINDOW_S * rate))
    sig = _channels(x)
    if sig.shape[0] < n * down:
        return np.zeros(0), np.zeros(0)
    low = resample_poly(sig, 1, down, axis=0)
    own = sosfiltfilt(butter(4, LOW_SPECTRUM_HZ, btype="highpass", fs=rate, output="sos"), low, axis=0)
    span = np.ones(max(1, int(round(0.01 * rate))))
    own_db = 10 * np.log10(np.maximum(np.convolve(np.mean(own ** 2, axis=1), span / span.size, "same"), 1e-30))
    all_db = 10 * np.log10(np.maximum(np.convolve(np.mean(low ** 2, axis=1), span / span.size, "same"), 1e-30))
    rest = (own_db <= np.percentile(own_db, 95) - ACTIVE_RANGE_DB) & (all_db > SILENCE_DB)
    count = np.concatenate([[0], np.cumsum(rest)])
    starts = np.flatnonzero(count[n:] - count[:-n] == n)  # every window lying wholly in a rest
    if starts.size == 0:
        return np.zeros(0), np.zeros(0)
    starts = starts[_evenly_spread(starts.size, MAX_REST_WINDOWS)]
    windows = np.stack([low[s:s + n] for s in starts])  # windows × samples × channels
    hann = np.hanning(n)[None, :, None]
    spectrum = np.abs(np.fft.rfft((windows - windows.mean(axis=1, keepdims=True)) * hann, axis=1)) ** 2
    power = spectrum.mean(axis=(0, 2)) / (n * np.sum(hann ** 2))  # Parseval: the bins add up to the power
    power[1:] *= 2  # one-sided
    freqs = np.fft.rfftfreq(n, 1 / rate)
    keep = freqs < REST_SPECTRUM_HZ
    return freqs[keep], power[keep] / sung_power


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


def _evenly_spread(count: int, most: int) -> np.ndarray:
    """Indices of at most ``most`` of ``count`` items, evenly spread."""
    return np.arange(count) if count <= most else np.linspace(0, count - 1, most).astype(int)


def spectral_envelope(sung: np.ndarray, fs: float, frame_s: float = 0.03, nfft: int = 2048
                      ) -> tuple[np.ndarray, np.ndarray]:
    """Average LPC envelope of the voice (dB): the shape of the sound, without the notes.

    Linear prediction follows the resonances of the voice and of the room;
    averaging over many syllables then flattens the moving vowel formants
    and keeps what never moves. The channels' autocorrelations are added
    (their powers, not their mono fold). At this order the low frequencies
    stay blurred: Eden reads it above HARMONIC_HIGH_HZ only.
    """
    order = int(fs / 1000) + 4
    n = int(frame_s * fs)
    freqs = np.linspace(0, fs / 2, nfft, endpoint=False)
    pick = _evenly_spread(sung.shape[0] // n, MAX_ENVELOPE_FRAMES)
    window = np.hanning(n)
    r = sum(autocorrelation(frame_matrix(sung[:, c], n, n)[pick] * window, order) for c in range(sung.shape[1]))
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


PITCH_FRAME_S = 0.04
MAX_PITCH_FRAMES = 1500  # evenly spread over the song: plenty for percentiles and averages
PITCH_MIN_HZ, PITCH_MAX_HZ = 60.0, 1000.0


def pitch_frames(sung: np.ndarray, fs: float) -> np.ndarray:
    """40 ms frames of the sung voice, at most MAX_PITCH_FRAMES evenly spread (frames × samples × channels)."""
    n = int(PITCH_FRAME_S * fs)
    count = sung.shape[0] // n
    return sung[: count * n].reshape(count, n, sung.shape[1])[_evenly_spread(count, MAX_PITCH_FRAMES)]


def frame_pitches(frames: np.ndarray, fs: float) -> np.ndarray:
    """Pitch of each frame (Hz), NaN where it is not clearly periodic (autocorrelation peak ≤ 0.6).

    The channels' autocorrelations are added, so a widened voice keeps its pitch.
    """
    lag_min, lag_max = int(fs / PITCH_MAX_HZ), int(fs / PITCH_MIN_HZ)
    if frames.shape[0] == 0 or lag_max >= frames.shape[1]:
        return np.full(frames.shape[0], np.nan)
    centred = frames - frames.mean(axis=1, keepdims=True)
    ac = sum(autocorrelation(centred[:, :, c], lag_max) for c in range(frames.shape[2]))
    sounding = ac[:, 0] >= 1e-10
    region = ac[:, lag_min:lag_max + 1] / np.where(sounding, ac[:, 0], 1.0)[:, None]
    lags = lag_min + np.argmax(region, axis=1)
    return np.where(sounding & (region.max(axis=1) > 0.6), fs / lags, np.nan)


def lowest_f0(pitches: np.ndarray) -> float | None:
    """Lowest sustained pitch (5th percentile of the clearly periodic frames), in Hz."""
    found = pitches[np.isfinite(pitches)]
    return float(np.percentile(found, 5)) if found.size >= 10 else None


def frequent_pitches(pitches: np.ndarray) -> list[float]:
    """Notes the voice dwells on (Hz): semitones holding more than FREQUENT_NOTE_SHARE of the pitched frames."""
    found = pitches[np.isfinite(pitches)]
    if found.size == 0:
        return []
    semitones, counts = np.unique(np.round(12 * np.log2(found / 440.0)), return_counts=True)
    return [float(440.0 * 2 ** (s / 12)) for s in semitones[counts > FREQUENT_NOTE_SHARE * found.size]]


def near_sung_notes(hz: float, notes: list[float]) -> bool:
    """Within 1/6 octave of a note the voice dwells on, or of that note's 2nd harmonic."""
    return any(abs(math.log2(hz / (k * note))) <= 1 / 6 for note in notes for k in (1, 2))


def note_groups(pitches: np.ndarray) -> np.ndarray:
    """The note of each frame: 0, 1, … (−1 where the frame has no clear pitch).

    The span of one semitone holding the most pitched frames is the first
    note; its frames are set aside and the next span is sought among the
    others, until every pitched frame has its note. Unlike rounding to the
    nearest semitone, a note sung between two semitones (240 Hz with its
    vibrato) stays one note instead of two; a vibrato wider than a semitone
    end to end still makes two.
    """
    semitones = 12 * np.log2(pitches / 440.0)
    labels = np.full(pitches.size, -1)
    left = np.flatnonzero(np.isfinite(pitches))
    note = 0
    while left.size:
        values = np.sort(semitones[left])
        held = np.searchsorted(values, values + 1.0, side="right") - np.arange(values.size)
        start = values[int(np.argmax(held))]
        span = (semitones[left] >= start) & (semitones[left] <= start + 1.0)
        labels[left[span]] = note
        left = left[~span]
        note += 1
    return labels


HARMONIC_TOP_HZ = 4000.0  # harmonics are read up to here (the neighbours of those near 2 kHz)
BANDS_PER_OCTAVE = 24
MIN_SAMPLES = 20  # harmonics a band needs before it is judged
NARROW = np.ones(3)  # the band and its neighbours: 1/8 octave
RING = np.r_[np.ones(5), np.zeros(7), np.ones(5)]  # the bands 1/6 to 1/3 octave away, on both sides
THIRD = np.r_[0.5, np.ones(7), 0.5]  # 1/3 octave (8 bands, half of each end band)


@dataclass
class HarmonicProfile:
    """How much the voice's harmonics stick out of their neighbours, pooled in 1/24-octave bands."""
    centres: np.ndarray
    sums: np.ndarray  # dB, summed over the harmonics that fell in each band
    counts: np.ndarray
    lifted: np.ndarray  # how many of those harmonics stood above their neighbours' line

    def mean(self, kernel: np.ndarray) -> np.ndarray:
        """Mean over the bands ``kernel`` covers around each band (NaN with too few harmonics)."""
        return self._over(self.sums, kernel)

    def lifted_share(self, kernel: np.ndarray) -> np.ndarray:
        """Share of the harmonics above their neighbours' line over the bands ``kernel`` covers
        (NaN with too few harmonics)."""
        return self._over(self.lifted, kernel)

    def _over(self, values: np.ndarray, kernel: np.ndarray) -> np.ndarray:
        total = np.convolve(values, kernel, mode="same")
        count = np.convolve(self.counts, kernel, mode="same")
        return np.where(count >= MIN_SAMPLES, total / np.maximum(count, 1), np.nan)


def harmonic_profile(frames: np.ndarray, pitches: np.ndarray, fs: float) -> HarmonicProfile:
    """Level of every harmonic of the pitched frames relative to the straight line (dB against log
    frequency) through the other harmonics of the same frame, up to one octave away on each side.

    A fixed resonance lifts the harmonics near it on every note, every time;
    a vowel formant moves from syllable to syllable. A fundamental has no
    harmonic below it and is never judged, so the sung notes themselves
    cannot pass for resonances.
    """
    edges = 75.0 * 2 ** (np.arange(int(math.log2(HARMONIC_TOP_HZ / 75.0) * BANDS_PER_OCTAVE) + 1)
                         / BANDS_PER_OCTAVE)
    centres = np.sqrt(edges[:-1] * edges[1:])
    pitched = np.isfinite(pitches)
    if not pitched.any():
        return HarmonicProfile(centres, np.zeros(centres.size), np.zeros(centres.size), np.zeros(centres.size))
    frames, f0 = frames[pitched], pitches[pitched]
    n = frames.shape[1]
    nfft = 1 << int(math.ceil(math.log2(2 * n)))
    window = np.hanning(n)
    power = sum(np.abs(np.fft.rfft(frames[:, :, c] * window, nfft, axis=1)) ** 2
                for c in range(frames.shape[2])) / frames.shape[2]
    step = fs / nfft
    top = min(HARMONIC_TOP_HZ, 0.45 * fs)
    order = np.arange(1, int(top / f0.min()) + 1)
    freq = f0[:, None] * order
    valid = freq < top
    # each harmonic's level: the strongest bin within a quarter of the pitch around it
    reach = np.maximum(1, np.round(0.25 * f0 / step)).astype(int)
    offsets = np.arange(-reach.max(), reach.max() + 1)
    bins = np.clip(np.round(freq / step).astype(int)[:, :, None] + offsets, 0, power.shape[1] - 1)
    peak = np.where(np.abs(offsets) <= reach[:, None, None],
                    power[np.arange(f0.size)[:, None, None], bins], 0.0).max(axis=2)
    level = 10 * np.log10(np.maximum(peak, 1e-30))
    # least-squares line through the neighbours (same weights for each), read at the harmonic itself
    octaves = np.log2(order[None, :] / order[:, None])  # [i, j]: where harmonic j sits seen from harmonic i
    near = ((np.abs(octaves) <= 1.0) & (octaves != 0)).astype(float)
    w = valid.astype(float)
    wy = w * np.where(valid, level, 0.0)
    s0, s1, s2 = w @ near.T, w @ (near * octaves).T, w @ (near * octaves ** 2).T
    sy, sxy = wy @ near.T, wy @ (near * octaves).T
    below, above = w @ (near * (octaves < 0)).T, w @ (near * (octaves > 0)).T
    det = s0 * s2 - s1 * s1
    judged = valid & (below >= 1) & (above >= 1) & (det > 1e-12)
    line = (s2 * sy - s1 * sxy) / np.where(judged, det, 1.0)
    band = np.searchsorted(edges, freq) - 1
    keep = judged & (band >= 0) & (band < centres.size)
    lift = (level - line)[keep]
    sums = np.bincount(band[keep], lift, centres.size)
    counts = np.bincount(band[keep], None, centres.size).astype(float)
    lifted = np.bincount(band[keep], (lift > 0).astype(float), centres.size)
    return HarmonicProfile(centres, sums, counts, lifted)


def note_profiles(frames: np.ndarray, pitches: np.ndarray, fs: float) -> list[HarmonicProfile]:
    """The harmonic profile of each sung note on its own (notes as ``note_groups`` finds them)."""
    labels = note_groups(pitches)
    return [harmonic_profile(frames[labels == note], pitches[labels == note], fs)
            for note in range(int(labels.max(initial=-1)) + 1)]


def find_resonances(profile: HarmonicProfile, envelope: tuple[np.ndarray, np.ndarray], notes: list[float],
                    max_count: int = 3) -> list[Resonance]:
    """Fixed narrow bumps of the voice (room or microphone resonances), at least 1/3 octave apart.

    150–2000 Hz: harmonics standing RESONANCE_MIN_DB above their neighbours'
    line (over 1/8 octave), and as much above the bands 1/6 to 1/3 octave
    away (a vowel formant spreads wider). 2–8 kHz: the LPC envelope
    RESONANCE_MIN_DB above its one-octave average. Nothing within 1/6
    octave of a note the voice dwells on or of its octave. The thresholds
    are strict on purpose: a missed resonance costs less than notching notes
    the artist wants.
    """
    narrow = profile.mean(NARROW)
    with np.errstate(invalid="ignore"):
        low = ((profile.centres >= ANALYSIS_LOW_HZ) & (profile.centres < HARMONIC_HIGH_HZ)
               & (narrow >= RESONANCE_MIN_DB) & (narrow - profile.mean(RING) >= RESONANCE_MIN_DB))
    freqs, env = envelope
    sel = (freqs >= HARMONIC_HIGH_HZ / 2 ** 0.5) & (freqs <= ANALYSIS_HIGH_HZ)
    f, excess = freqs[sel], _excess_over_octave(freqs[sel], env[sel])
    high = (f >= HARMONIC_HIGH_HZ) & (excess >= RESONANCE_MIN_DB)
    cand_hz = np.concatenate([profile.centres[low], f[high]])
    cand_db = np.concatenate([narrow[low], excess[high]])
    found: list[Resonance] = []
    for i in np.argsort(cand_db)[::-1]:
        if len(found) >= max_count:
            break
        if not near_sung_notes(cand_hz[i], notes) and all(
                abs(math.log2(cand_hz[i] / r.freq_hz)) > 1 / 3 for r in found):
            found.append(Resonance(float(cand_hz[i]), float(cand_db[i])))
    return sorted(found, key=lambda r: r.freq_hz)


def low_mid_buildup(profile: HarmonicProfile, per_note: list[HarmonicProfile], notes: list[float]
                    ) -> tuple[float, float, int]:
    """(centre, excess dB, notes that show it) of the strongest bump between 150 and 500 Hz: the
    harmonics' lift over their neighbours' line, averaged over 1/3 octave (a broad bump: proximity
    effect, boxiness).

    A band counts only when at least two sung notes (``per_note``) show the
    bump on their own, from their harmonics in that 1/3 octave: lifted by
    LOW_MID_MIN_DB − 1 dB or more on average, and above their neighbours'
    line in at least LOW_MID_STEADY_SHARE of the cases. A fixed bump lifts
    the harmonics of every note there, every time; the vowels' first formant
    lifts the 2nd harmonic of a high voice's lowest notes (240–250 Hz, just
    under 500 Hz) only when the vowel puts it there, and one note that
    happens to meet such vowels more often is no bump either. The excess is
    the lift of all the harmonics there, every note pooled. A voice that
    sings a single note with harmonics in the band gets no bump: a missed
    cut costs less than a wrong one. Only bands whose own 1/8 octave holds
    harmonics count: the average must not place a bump where no harmonic
    was measured (a voice whose lowest 2nd harmonic is 524 Hz would
    otherwise get a "bump" at 469 Hz from that harmonic alone). Bands within
    1/6 octave of a note the voice dwells on, or of its octave, are left out.
    """
    third = profile.mean(THIRD)
    zone = ((profile.centres >= 150) & (profile.centres <= 500) & np.isfinite(third)
            & np.isfinite(profile.mean(NARROW)))
    zone &= np.array([not near_sung_notes(c, notes) for c in profile.centres])
    seen = np.zeros(profile.centres.size, dtype=int)
    with np.errstate(invalid="ignore"):
        for note in per_note:
            seen += ((note.mean(THIRD) >= LOW_MID_MIN_DB - 1)
                     & (note.lifted_share(THIRD) >= LOW_MID_STEADY_SHARE))
    zone &= seen >= 2
    if not zone.any():
        return 300.0, 0.0, 0
    i = int(np.argmax(np.where(zone, third, -math.inf)))
    return float(profile.centres[i]), float(max(third[i], 0.0)), int(seen[i])


def _frames_psd(x: np.ndarray, fs: float, frames: np.ndarray, size: int) -> tuple[np.ndarray, np.ndarray]:
    """Welch spectrum (dB, channels' powers averaged) of the 1 ms frames selected by ``frames``."""
    mask = np.repeat(frames, size)
    chosen = _channels(x)[: mask.size][mask]
    if chosen.shape[0] < 4096:
        return np.zeros(0), np.zeros(0)
    return _psd_db(chosen, fs)


def sibilant_peak(x: np.ndarray, fs: float, s_frames: np.ndarray, size: int) -> float | None:
    """Frequency of the 's' sounds' spectral peak (3–10 kHz), from the 's' frames only."""
    freqs, psd = _frames_psd(x, fs, s_frames, size)
    sel = (freqs >= 3000) & (freqs <= 10000)
    if not sel.any():
        return None
    return float(freqs[sel][np.argmax(psd[sel])])


def deess_band_low_hz(sibilant_peak_hz: float | None) -> float:
    """Lower edge of the de-esser's band: 0.7 × the 's' peak, kept within 3.5–8 kHz (4.5 kHz when the
    peak is unknown). The measure that triggers a de-esser and the de-esser itself both use it."""
    return min(8000.0, max(3500.0, 0.7 * sibilant_peak_hz)) if sibilant_peak_hz else 4500.0


def air(x: np.ndarray, fs: float, vowel_frames: np.ndarray, size: int) -> float:
    """Energy above 8 kHz relative to 2–5 kHz on the vowels (negative: dull top end)."""
    freqs, psd = _frames_psd(x, fs, vowel_frames, size)
    if freqs.size == 0:
        return -math.inf
    return _band_db(freqs, psd, 8000, min(16000, fs / 2)) - _band_db(freqs, psd, 2000, 5000)


def sibilant_frames(x: np.ndarray, fs: float, level: np.ndarray, active: np.ndarray
                    ) -> tuple[np.ndarray, np.ndarray]:
    """('s' frames, vowel frames) among the active 1 ms frames.

    A frame is an 's' when the band above 4.5 kHz carries most of its energy,
    a vowel when that band is far below (both levels are the channels'
    powers averaged).
    """
    high, _ = split_band(x, fs, 4500.0, None)
    hlevel, _ = band_levels_db(high, fs)
    n = min(hlevel.size, level.size)
    full, hi, act = level[:n], hlevel[:n], active[:n]
    return act & (hi - full > -3.0), act & (hi - full < -15.0)


def _vowel_db(level: np.ndarray, vowels: np.ndarray) -> float:
    return float(np.percentile(level[: vowels.size][vowels], 75)) if vowels.any() else -math.inf


def vowel_level(x: np.ndarray, fs: float, level: np.ndarray, active: np.ndarray) -> float:
    """Typical level of the vowels (75th percentile of their 1 ms frames): the de-essers' reference."""
    return _vowel_db(level, sibilant_frames(x, fs, level, active)[1])


def sibilant_excess(x: np.ndarray, fs: float, s_frames: np.ndarray, vowel_db: float, low_hz: float) -> float:
    """Loud 's' minus the vowels (dB): 90th percentile of the 's' frames' level in the de-esser's
    band (above ``low_hz``), the level the de-esser compares with its threshold (vowels − N dB)."""
    if not s_frames.any() or not math.isfinite(vowel_db):
        return -math.inf
    band, _ = split_band(x, fs, low_hz, None)
    blevel, _ = band_levels_db(band, fs)
    n = min(blevel.size, s_frames.size)
    return float(np.percentile(blevel[:n][s_frames[:n]], 90)) - vowel_db


def _inside_phrases(active: np.ndarray, size: int, fs: float, count: int) -> np.ndarray:
    """400 ms loudness blocks (100 ms apart) whose 1 ms frames are at least 90 % sung.

    The blocks are placed in samples, exactly like ``block_loudness``: at
    44.1 kHz a 1 ms frame is 44 samples, and counting in frames would drift
    by half a second over a song.
    """
    cumulative = np.concatenate([[0], np.cumsum(active)])
    block = int(round(0.4 * fs))
    step = max(1, int(round(block * 0.25)))
    starts = np.minimum(np.arange(count) * step // size, active.size)
    ends = np.minimum((np.arange(count) * step + block) // size, active.size)
    sung = (cumulative[ends] - cumulative[starts]) / np.maximum(ends - starts, 1)
    return sung >= 0.9


def measure_vocal(x: np.ndarray, fs: float) -> VocalMeasure:
    level, active, size = active_frames(x, fs)
    if not active.any():
        return VocalMeasure(-math.inf, 0.0)
    sung = sung_samples(x, active, size)
    freqs, psd = _psd_db(sung, fs)
    blocks = block_loudness(x, fs)
    lufs = gated_loudness(blocks)
    active_blocks = np.isfinite(blocks) & (blocks > lufs - 10)
    sung_blocks = blocks[active_blocks & _inside_phrases(active, size, fs, blocks.size)]

    s_frames, vowel_frames = sibilant_frames(x, fs, level, active)
    vowel = _vowel_db(level, vowel_frames)
    peak = sibilant_peak(x, fs, s_frames, size)
    frames = pitch_frames(sung, fs)
    pitches = frame_pitches(frames, fs)
    resonances: list[Resonance] = []
    low_mid_hz, low_mid_excess, low_mid_notes = 300.0, 0.0, 0
    if sung.shape[0] >= 4 * fs:
        notes = frequent_pitches(pitches)
        profile = harmonic_profile(frames, pitches, fs)
        resonances = find_resonances(profile, spectral_envelope(sung, fs), notes)
        low_mid_hz, low_mid_excess, low_mid_notes = low_mid_buildup(
            profile, note_profiles(frames, pitches, fs), notes)
    sung_power = max(float(np.mean(sung ** 2)), 1e-30)
    low_hz, low_share = _low_spectrum(sung, fs, sung_power)
    rest_low_hz, rest_low_share = _rest_low_spectrum(x, fs, sung_power)

    sung_level = level[active]
    rms_db = 10 * math.log10(np.mean(10 ** (sung_level / 10)))
    peak_db = 20 * math.log10(max(float(np.max(np.abs(x))), 1e-12))
    return VocalMeasure(
        loudness_lufs=lufs,
        mud_db=_band_db(freqs, psd, 200, 500) - _band_db(freqs, psd, 1000, 4000),
        resonances=resonances,
        sibilant_excess_db=sibilant_excess(x, fs, s_frames, vowel, deess_band_low_hz(peak)),
        sibilant_share=float(s_frames.sum() / active[: s_frames.size].sum()),
        dynamic_spread_db=float(np.percentile(sung_blocks, 90) - np.percentile(sung_blocks, 10))
        if sung_blocks.size >= 4 else 0.0,
        crest_db=peak_db - rms_db,
        sung_p70_db=float(np.percentile(sung_level, 70)),
        lowest_f0_hz=lowest_f0(pitches),
        sibilant_peak_hz=peak,
        low_mid_hz=low_mid_hz,
        low_mid_excess_db=low_mid_excess,
        low_mid_notes=low_mid_notes,
        air_db=air(x, fs, vowel_frames, size),
        low_hz=low_hz,
        low_share=low_share,
        rest_low_hz=rest_low_hz,
        rest_low_share=rest_low_share,
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
    voice_db: float  # the voice in this band relative to its strongest band


MASKING_FFT, MASKING_HOP = 4096, 1024
MASKING_CHUNK = 256  # STFT frames transformed at once (about 6 s at 44.1 kHz)


def _band_power(x: np.ndarray, fs: float, mask: np.ndarray, edges: list[tuple[float, float]]
                ) -> np.ndarray:
    """Mean power per band over the STFT frames that fall in the selected 400 ms blocks.

    The STFT (Hann, 4096 points, hop 1024, end zero-padded) is computed one
    channel and a few seconds at a time, in single precision, for the
    selected frames only, and the channels' powers are added (like BS.1770):
    a whole-song stereo STFT would hold gigabytes.
    """
    two_d = _channels(x)
    count = (max(two_d.shape[0], MASKING_FFT) - MASKING_FFT + MASKING_HOP - 1) // MASKING_HOP + 1
    times = (np.arange(count) * MASKING_HOP + MASKING_FFT / 2) / fs
    block = np.clip(np.round((times - 0.2) / 0.1).astype(int), 0, max(mask.size - 1, 0))
    chosen = np.flatnonzero(mask[block]) if mask.size else np.zeros(0, dtype=int)
    if chosen.size == 0:
        return np.full(len(edges), np.nan)
    window = get_window("hann", MASKING_FFT)
    window = (window / window.sum()).astype(np.float32)
    total = np.zeros(MASKING_FFT // 2 + 1)
    for c in range(two_d.shape[1]):
        sig = np.zeros((count - 1) * MASKING_HOP + MASKING_FFT, dtype=np.float32)
        sig[: two_d.shape[0]] = two_d[:, c]
        frames = frame_matrix(sig, MASKING_FFT, MASKING_HOP)
        for start in range(0, chosen.size, MASKING_CHUNK):
            z = fft.rfft(frames[chosen[start:start + MASKING_CHUNK]] * window, axis=1)
            total += (z.real ** 2 + z.imag ** 2).sum(axis=0, dtype=np.float64)
    mean = total / chosen.size
    freqs = fft.rfftfreq(MASKING_FFT, 1 / fs)
    return np.array([mean[(freqs >= lo) & (freqs < hi)].sum() for lo, hi in edges])


def band_masking(vocal: np.ndarray, other: np.ndarray, fs: float, mask: np.ndarray
                 ) -> list[BandMasking]:
    """How much ``other`` covers the voice in each 1/3-octave band centred from 250 Hz to 8 kHz
    while the voice sings, with the band's importance for intelligibility (SII: a third of its
    octave's weight) and the voice's level there."""
    bands = []
    for i in range(16):  # centres 250 · 2^(i/3) Hz: 250 Hz … 8 kHz
        fc = 250 * 2 ** (i / 3)
        lo, hi = fc / 2 ** (1 / 6), fc * 2 ** (1 / 6)
        if hi < fs / 2:
            bands.append((lo, hi, SII_OCTAVE_WEIGHTS[250 * 2 ** round(i / 3)] / 3))
    edges = [(lo, hi) for lo, hi, _ in bands]
    pv, po = _band_power(vocal, fs, mask, edges), _band_power(other, fs, mask, edges)
    strongest = max((v for v in pv if v > 0), default=0.0)
    out = []
    for (lo, hi, weight), v, o in zip(bands, pv, po, strict=True):
        if v > 0 and o > 0:
            out.append(BandMasking(lo, hi, 10 * math.log10(o / v), weight, 10 * math.log10(v / strongest)))
    return out
