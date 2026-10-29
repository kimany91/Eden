"""Key of the song and pitch of the 808, from the instrumental parts.

Chroma (energy per pitch class) is computed from the spectral peaks of a
high-resolution STFT, on a semitone grid shifted to the beat's own tuning
(a beat tuned to A = 432 Hz is 32 cents flat: on a 440 grid a third of
every note would leak into the semitone below). It is correlated with the
24 rotations of three tonal profiles that suit popular and electronic
music: Krumhansl & Kessler (1982), Shaath (KeyFinder) and Faraldo's EDM
profile (Essentia "edma") — the Temperley–Kostka–Payne profile is not used,
it tends to name the relative major of minor loops. Relative major and
minor keys share the same seven notes: the 808 settles which one is the
tonic whenever it plays one of the two tonics clearly more. For mixing
decisions only the scale matters, and relative keys share the same scale.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.signal import stft

NOTE_NAMES = ["Do", "Do#", "Ré", "Mi♭", "Mi", "Fa", "Fa#", "Sol", "La♭", "La", "Si♭", "Si"]

# Krumhansl & Kessler (1982) probe-tone ratings
KK_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
KK_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
# Shaath, KeyFinder (tuned on popular and electronic music)
SHAATH_MAJOR = [6.6, 2.0, 3.5, 2.3, 4.6, 4.0, 2.5, 5.2, 2.4, 3.7, 2.3, 3.4]
SHAATH_MINOR = [6.5, 2.7, 3.5, 5.4, 2.6, 3.5, 2.5, 5.2, 4.0, 2.7, 4.3, 3.2]
# Faraldo et al. 2016, Essentia "edma" (electronic dance music)
EDMA_MAJOR = [1.00, 0.29, 0.50, 0.40, 0.60, 0.56, 0.32, 0.80, 0.31, 0.45, 0.42, 0.39]
EDMA_MINOR = [1.00, 0.31, 0.44, 0.58, 0.33, 0.49, 0.29, 0.78, 0.43, 0.29, 0.53, 0.32]
PROFILES = ((KK_MAJOR, KK_MINOR), (SHAATH_MAJOR, SHAATH_MINOR), (EDMA_MAJOR, EDMA_MINOR))
BASS_DECIDES = 1.5  # the 808 settles relative keys when one tonic gets this much more of its time


@dataclass
class Key:
    tonic: int  # pitch class, 0 = C
    minor: bool
    correlation: float  # mean correlation of the profiles with the song's chroma
    margin: float  # how far ahead of the second-best key
    confidence: str  # haute | moyenne | faible
    chroma: list[float]
    relative_close: bool = False  # the relative key scored almost as well and the 808 did not settle it
    tuning_cents: float = 0.0  # the beat's tuning relative to A = 440 Hz
    decided_by_bass: bool = False

    @property
    def name(self) -> str:
        return f"{NOTE_NAMES[self.tonic]} {'mineur' if self.minor else 'majeur'}"

    @property
    def relative(self) -> Key:
        tonic = (self.tonic + 3) % 12 if self.minor else (self.tonic + 9) % 12
        return Key(tonic, not self.minor, self.correlation, self.margin, self.confidence, self.chroma,
                   tuning_cents=self.tuning_cents)

    @property
    def display(self) -> str:
        return f"{self.name} (ou {self.relative.name})" if self.relative_close else self.name

    @property
    def scale(self) -> set[int]:
        steps = (0, 2, 3, 5, 7, 8, 10) if self.minor else (0, 2, 4, 5, 7, 9, 11)
        return {(self.tonic + s) % 12 for s in steps}


def _mono(x: np.ndarray) -> np.ndarray:
    return x.mean(axis=1) if x.ndim == 2 else x


def _peaks(x: np.ndarray, fs: float, fmin: float, fmax: float) -> tuple[np.ndarray, np.ndarray]:
    """(MIDI pitch of each STFT bin, peak salience per bin and frame) between ``fmin`` and ``fmax``.

    Long windows (~1.5 s, ~0.7 Hz resolution) resolve the semitones of the low
    octaves (2.6 Hz apart around 45 Hz). Only spectral peaks count (leakage
    between partials would blur the profile), with linear magnitude.
    """
    nper = 1 << int(math.ceil(math.log2(fs * 1.4)))
    freqs, _, z = stft(_mono(x), fs=fs, nperseg=nper, noverlap=nper // 2, boundary=None)
    sel = (freqs >= fmin) & (freqs <= fmax)
    mag = np.abs(z[sel])
    if mag.size == 0 or mag.max() <= 0:
        return np.zeros(0), np.zeros((0, 0))
    is_peak = np.zeros_like(mag, dtype=bool)
    is_peak[1:-1] = (mag[1:-1] > mag[:-2]) & (mag[1:-1] >= mag[2:])
    return 69 + 12 * np.log2(freqs[sel] / 440.0), mag * is_peak


def tuning(x: np.ndarray, fs: float, fmin: float = 150.0, fmax: float = 2000.0) -> float:
    """Tuning of ``x`` in cents from A = 440 Hz: the most common deviation of its spectral
    peaks from the nearest semitone (1-cent histogram weighted by peak magnitude, mode
    wrapped to −35…+65 cents like Essentia's TuningFrequency)."""
    midi, salience = _peaks(x, fs, fmin, fmax)
    if midi.size == 0:
        return 0.0
    weight = salience.sum(axis=1)
    if weight.sum() <= 0:
        return 0.0
    cents = np.round(100 * (midi - np.round(midi))).astype(int)  # −50…+50
    hist = np.zeros(101)
    np.add.at(hist, cents + 50, weight)
    hist = hist[:-1] + np.r_[hist[-1], np.zeros(99)]  # +50 and −50 are the same deviation
    mode = int(np.argmax(np.convolve(np.r_[hist[-2:], hist, hist[:2]], np.ones(5) / 5, mode="valid"))) - 50
    return float(mode + 100 if mode < -35 else mode)


def chroma(x: np.ndarray, fs: float, fmin: float = 55.0, fmax: float = 2000.0, tuning_cents: float = 0.0
           ) -> np.ndarray:
    """Energy-weighted mean chroma (12 values, sum 1) between ``fmin`` and ``fmax``.

    Each peak's energy is shared between the two nearest pitch classes of the
    grid shifted by ``tuning_cents``, according to its distance in semitones.
    """
    midi, salience = _peaks(x, fs, fmin, fmax)
    if midi.size == 0:
        return np.zeros(12)
    midi = midi - tuning_cents / 100
    low = np.floor(midi).astype(int)
    upper = midi - low  # share going to the next semitone
    frames = np.zeros((12, salience.shape[1]))
    np.add.at(frames, low % 12, salience * (1 - upper)[:, None])
    np.add.at(frames, (low + 1) % 12, salience * upper[:, None])
    energy = frames.sum(axis=0)
    mean = (frames * energy).sum(axis=1)
    return mean / mean.sum() if mean.sum() > 0 else np.zeros(12)


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a - a.mean(), b - b.mean()
    den = math.sqrt(float((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / den) if den else 0.0


RELATIVE_CLOSE = 0.1  # score gap under which relative major/minor are considered tied


def detect_key(x: np.ndarray, fs: float, bass: np.ndarray | None = None, fmin: float = 55.0,
               tuning_cents: float | None = None) -> Key | None:
    """Most likely key of the harmony ``x``; ``bass`` (low-end chroma of the 808) settles which
    of two relative keys is the tonic. ``fmin`` 200 Hz keeps kick and 808 out of a full beat."""
    cents = tuning(x, fs) if tuning_cents is None else tuning_cents
    c = chroma(x, fs, fmin=fmin, tuning_cents=cents)
    if not c.any():
        return None
    scores = np.zeros(24)  # 0-11 major, 12-23 minor
    for major, minor in PROFILES:
        for tonic in range(12):
            scores[tonic] += _corr(c, np.roll(major, tonic))
            scores[12 + tonic] += _corr(c, np.roll(minor, tonic))
    scores /= len(PROFILES)
    best = int(np.argmax(scores))
    tonic, minor = best % 12, best >= 12
    rel = (tonic + 3) % 12 if minor else 12 + (tonic + 9) % 12
    relative_close = scores[best] - scores[rel] < RELATIVE_CLOSE
    decided = False
    if bass is not None and bass.any():
        mine, theirs = bass[tonic], bass[rel % 12]
        if theirs >= BASS_DECIDES * mine:
            best, rel = rel, best
            tonic, minor = best % 12, best >= 12
        decided = max(mine, theirs) >= BASS_DECIDES * min(mine, theirs)
    others = [scores[i] for i in range(24) if i not in (best, rel)]
    margin = float(scores[best] - max(others))  # lead over keys with a different scale
    corr = float(scores[best])
    confidence = "haute" if corr > 0.75 and margin > 0.05 else "moyenne" if corr > 0.55 else "faible"
    return Key(tonic, minor, corr, margin, confidence, [float(v) for v in c],
               bool(relative_close and not decided), cents, decided)


def bass_pitch_classes(x: np.ndarray, fs: float, tuning_cents: float = 0.0, fmin: float = 30.0,
                       fmax: float = 160.0) -> np.ndarray:
    """Share of the low-frequency energy carried by each pitch class (808 / bass notes)."""
    return chroma(x, fs, fmin, fmax, tuning_cents)


def root_note(bass_chroma: np.ndarray) -> int | None:
    return int(np.argmax(bass_chroma)) if bass_chroma.any() else None
