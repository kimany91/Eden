"""Synthetic rap-like voices and beats with controllable defects (tests only)."""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfilt

from eden.mix.dsp import apply_sos, peaking_sos

FS = 44100


def voice(seconds: float = 24.0, seed: int = 1, *, notes: list[float] | None = None,
          resonance_hz: float | None = None, rumble: float = 0.0, sibilance: float = 0.3,
          phrase_spread_db: float = 4.0, level: float = 0.25, breaths: float = 0.0) -> np.ndarray:
    """Mono voice: syllables on changing notes, vowel formants, 's' bursts, pauses.

    ``sibilance`` is the peak of the 's' bursts relative to the vowels' peak
    (0.3 ≈ −10 dB, a normal voice; above 1, piercing sibilants).
    ``breaths``: a breath before each phrase, its peak this fraction of the
    vowels' (0.2 ≈ −14 dB, the loud breaths of a close mic).
    """
    rng = np.random.default_rng(seed)
    n = int(seconds * FS)
    t = np.arange(n) / FS
    notes = notes or [110, 123, 131, 147, 165, 98, 117, 139]
    note_len = int(0.35 * FS)
    f0 = np.repeat(rng.choice(notes, size=n // note_len + 1), note_len)[:n]
    f0 = f0 * (1 + 0.004 * np.sin(2 * np.pi * 5.5 * t))
    phase = 2 * np.pi * np.cumsum(f0) / FS
    src = sum(np.sin(h * phase) / h for h in range(1, 40) if h * 160 < FS / 2)
    # vowel formants that change with the syllables
    out = np.zeros(n)
    syl = int(0.18 * FS)
    for start in range(0, n, syl):
        seg = src[start:start + syl]
        f1, f2 = rng.uniform(450, 800), rng.uniform(1100, 2200)
        y = apply_sos(seg, peaking_sos(FS, f1, 3, 12)) + apply_sos(seg, peaking_sos(FS, f2, 4, 9))
        env = np.sin(np.linspace(0, np.pi, seg.size)) ** 0.6
        out[start:start + seg.size] = y * env
    out = out / (np.max(np.abs(out)) + 1e-12)
    # sibilants
    sib_sos = butter(4, [5000, 9500], btype="bandpass", fs=FS, output="sos")
    for start in rng.choice(np.arange(0, n - 4000, syl), size=int(seconds * 1.5), replace=False):
        burst = sosfilt(sib_sos, rng.normal(0, 1, 3000)) * np.hanning(3000)
        out[start:start + 3000] += sibilance * burst / (np.max(np.abs(burst)) + 1e-12)
    # phrases: 4 s sung, 1 s pause, each phrase at its own level
    phrase = np.ones(n)
    for start in range(0, n, 5 * FS):
        phrase[start:start + 4 * FS] = 10 ** (rng.uniform(-phrase_spread_db, phrase_spread_db) / 2 / 20)
        phrase[start + 4 * FS:start + 5 * FS] = 0
    out = out * phrase
    if breaths:
        sos = butter(4, [1500, 6000], btype="bandpass", fs=FS, output="sos")
        length = int(0.35 * FS)
        window = np.hanning(length)
        for start in range(5 * FS, n, 5 * FS):  # in the pause, just before the next phrase
            at = start - int(0.5 * FS)
            burst = sosfilt(sos, rng.normal(0, 1, length)) * window
            out[at:at + length] += breaths * burst / (np.max(np.abs(burst)) + 1e-12)
    out = out / (np.max(np.abs(out)) + 1e-12) * level
    if resonance_hz:
        out = apply_sos(out, peaking_sos(FS, resonance_hz, 12, 10))
    if rumble:
        out = out + rumble * sosfilt(butter(2, 50, fs=FS, output="sos"), rng.normal(0, 1, n))
    return np.stack([out, out], axis=1)


def beat(seconds: float = 24.0, seed: int = 2, level: float = 0.3) -> np.ndarray:
    """Stereo beat: kick, hats and a chord pad with energy in the presence band."""
    rng = np.random.default_rng(seed)
    n = int(seconds * FS)
    t = np.arange(n) / FS
    pad = sum(np.sin(2 * np.pi * f * t) for f in (220, 277, 330, 1760, 2200, 2640, 3300)) / 7
    kick = np.zeros(n)
    k = np.exp(-np.arange(int(0.25 * FS)) / (0.06 * FS)) * np.sin(2 * np.pi * 55 * np.arange(int(0.25 * FS)) / FS)
    for start in range(0, n - k.size, int(0.5 * FS)):
        kick[start:start + k.size] += k
    hats = sosfilt(butter(4, 8000, btype="highpass", fs=FS, output="sos"), rng.normal(0, 0.2, n))
    hats *= (np.arange(n) % int(0.125 * FS) < 0.02 * FS)
    mono = 0.5 * pad + kick + hats
    mono = mono / np.max(np.abs(mono)) * level
    return np.stack([mono, 0.95 * mono], axis=1)
