"""What an audio file sounds like, whatever it is called: a voice or an instrument.

Everyone names their tracks their own way ("kim 3", "VOICE", "mbappé", the beat's name...), so Eden
listens to the files. A voice recorded at the mic is mono (both sides the same, or the mic on one side
only), holds little below 60 Hz (a deep voice close to the mic stays above it; a kick or an 808 does
not), and stops between its phrases (the beat heard in the headphones, leaking into the mic, is far
below it). An instrument is mostly low end, or is stereo and never stops. What fits neither is left
to the names. The thresholds are Eden's choices.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

SUB_HZ = 60.0  # below it: kick and 808, not a voice
VOICE_MAX_SUB = 0.10  # share of the energy below SUB_HZ a mic recording of a voice stays under
INSTRUMENT_MIN_SUB = 0.25  # share from which a file is mostly a kick, an 808, a bass
NEAR_MONO = 0.95  # correlation of the two sides of a stereo file holding one mono recording
ONE_SIDE_DB = 20.0  # a side this much quieter than the other is empty: the mic was on one side only
BLOCK_S = 0.05
ACTIVE_DB = 20.0  # a block sounds when it is within this of the file's loud blocks (headphone leak is below)
VOICE_MAX_ACTIVE = 0.9  # share of the time a voice sounds at most: it breathes between its phrases
INSTRUMENT_MIN_ACTIVE = 0.95  # a beat or a loop does not stop
MIN_SECONDS = 3.0  # shorter (a kick, a clap, a "yeah"): its name says more
MAX_SECONDS = 600.0  # heard up to there
FFT_SIZE = 8192
MAX_SEGMENTS = 400


@dataclass
class Heard:
    kind: str  # "voice" | "instrument" | "unsure"
    sub_share: float  # of the energy, below SUB_HZ
    active_share: float  # of the time, sounding
    active_seconds: float
    mono: bool  # one channel, or two that are the same
    reason: str


def listen(path: str | Path) -> Heard | None:
    """What ``path`` sounds like; None when it cannot be read or is too short to tell."""
    try:
        info = sf.info(str(path))
        if info.duration < MIN_SECONDS:
            return None
        data, sr = sf.read(str(path), dtype="float32", always_2d=True,
                           frames=int(min(info.duration, MAX_SECONDS) * info.samplerate))
    except Exception:
        return None
    if data.size == 0 or not np.any(data):
        return None
    mono = data.shape[1] == 1 or _correlation(data[:, 0], data[:, 1]) >= NEAR_MONO or _one_side(data)
    signal = data.mean(axis=1)
    sub = _sub_share(signal, sr)
    block = max(1, int(BLOCK_S * sr))
    blocks = signal.size // block
    rms = np.sqrt(np.mean(signal[:blocks * block].reshape(blocks, block).astype(np.float64) ** 2, axis=1))
    loud = float(np.percentile(rms, 95))
    active = float(np.mean(rms > loud * 10 ** (-ACTIVE_DB / 20))) if loud > 0 else 0.0
    seconds = active * blocks * block / sr
    what = (f"{'mono' if mono else 'stéréo'}, {sub * 100:.0f} % d'énergie sous {SUB_HZ:.0f} Hz, "
            f"son présent {active * 100:.0f} % du temps")
    if mono and sub < VOICE_MAX_SUB and active < VOICE_MAX_ACTIVE:
        return Heard("voice", sub, active, seconds, mono, f"À l'écoute, une voix ({what})")
    if sub >= INSTRUMENT_MIN_SUB or (not mono and active >= INSTRUMENT_MIN_ACTIVE):
        return Heard("instrument", sub, active, seconds, mono, f"À l'écoute, un instrument ({what})")
    return Heard("unsure", sub, active, seconds, mono, f"À l'écoute, rien de net ({what})")


def _one_side(data: np.ndarray) -> bool:
    level = np.sqrt(np.mean(data.astype(np.float64) ** 2, axis=0))
    quiet, loud = float(level.min()), float(level.max())
    return loud > 0 and quiet < loud * 10 ** (-ONE_SIDE_DB / 20)


def _correlation(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a.astype(np.float64), b.astype(np.float64)
    denom = float(np.sqrt(np.dot(a, a) * np.dot(b, b)))
    return float(np.dot(a, b)) / denom if denom > 0 else 1.0


def _sub_share(signal: np.ndarray, sr: int) -> float:
    """Share of the energy below SUB_HZ, from the spectra of up to MAX_SEGMENTS segments spread over the file."""
    size = min(FFT_SIZE, signal.size)
    starts = np.linspace(0, signal.size - size, num=min(MAX_SEGMENTS, max(1, signal.size // size))).astype(int)
    window = np.hanning(size)
    power = sum(np.abs(np.fft.rfft(signal[s:s + size] * window)) ** 2 for s in starts)
    freqs = np.fft.rfftfreq(size, 1 / sr)
    total = float(np.sum(power[freqs > 20]))
    return float(np.sum(power[(freqs > 20) & (freqs < SUB_HZ)])) / total if total > 0 else 0.0
