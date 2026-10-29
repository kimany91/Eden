"""The processing steps Eden can decide on, and how each one is applied.

Every decision is a ``Treatment``: what is done, why (the measurement that
triggered it) and its parameters. ``apply`` runs a list of them in order on
one signal and records, for the dynamic ones, how much they actually worked
(average and maximum gain reduction), so the user sees real numbers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from eden.mix import dsp
from eden.mix.analysis import active_frames, vowel_level
from eden.mix.loudness import integrated_loudness
from eden.mix.saturation import saturate


@dataclass
class Treatment:
    kind: str  # highpass | eq | shelf | deesser | compressor | parallel | saturation | makeup | gain | …
    label: str  # short French description shown to the user
    reason: str  # measurement that triggered it
    params: dict = field(default_factory=dict)
    measured: dict = field(default_factory=dict)  # filled while applying (gain reduction...)
    applied: bool = True  # False when the stage found nothing to do on the signal it received


def _record_gain(t: Treatment, gr_db: np.ndarray) -> None:
    active = gr_db[gr_db < -0.05]
    t.measured = {"reduction_mean_db": float(-active.mean()) if active.size else 0.0,
                  "reduction_max_db": float(-gr_db.min()) if gr_db.size else 0.0}


def _sung_percentile(y: np.ndarray, fs: float, pct: float) -> float:
    """Level (dB, 1 ms frames) reached by ``pct`` % of the moments the voice sounds."""
    level, active, _ = active_frames(y, fs)
    return float(np.percentile(level[active], pct)) if active.any() else -math.inf


def _threshold(y: np.ndarray, fs: float, p: dict) -> float:
    """A fixed ``threshold_db``, or one set on the signal the stage really receives: the level
    of the ``percentile`` of the sung moments, lowered so that level gets ``reduction_db``."""
    if "threshold_db" in p:
        return p["threshold_db"]
    slope = 1 - 1 / p["ratio"]
    return _sung_percentile(y, fs, p["percentile"]) - p["reduction_db"] / slope


IDLE_DB = 0.3  # a dynamic stage that never reduces more than this did nothing worth applying


def _vowel_level(y: np.ndarray, fs: float) -> float:
    level, active, _ = active_frames(y, fs)
    return vowel_level(y, fs, level, active)


def apply(x: np.ndarray, fs: float, treatments: list[Treatment], hold: np.ndarray | None = None
          ) -> np.ndarray:
    """``hold``: 1 ms frames where tail-safe compressors freeze their gain (effect tails).

    Dynamic stages read the level of the signal as it reaches them (after the
    stages before), so a chain of compressors stays as planned. A dynamic
    stage that would reduce less than ``IDLE_DB`` anywhere is not applied and
    is marked ``applied = False``. ``makeup`` gives back the loudness the
    chain took (BS.1770, the voice as it came in vs. as it goes out).
    """
    y = x
    for t in treatments:
        p = t.params
        if t.kind == "highpass":
            y = dsp.apply_sos(y, dsp.highpass_sos(fs, p["freq_hz"], p.get("q", 0.7071)))
        elif t.kind == "eq":
            y = dsp.apply_sos(y, dsp.peaking_sos(fs, p["freq_hz"], p["q"], p["gain_db"]))
        elif t.kind == "shelf":
            y = dsp.apply_sos(y, dsp.shelf_sos(fs, p["freq_hz"], p["gain_db"], high=p.get("high", True)))
        elif t.kind == "deesser":
            threshold = _vowel_level(y, fs) - p["below_vowels_db"]
            high, rest, gr, size = dsp.deess_gain_db(y, fs, threshold, p["max_reduction_db"],
                                                     low_hz=p.get("low_hz", 4500.0))
            _record_gain(t, gr)
            t.applied = t.measured["reduction_max_db"] >= IDLE_DB
            if t.applied:
                y = rest + dsp._apply_gain(high, dsp._to_samples(gr, size, y.shape[0]))
        elif t.kind == "compressor":
            gr, size = dsp.compressor_gain_db(
                y, fs, _threshold(y, fs, p), p["ratio"], attack_ms=p["attack_ms"],
                release_ms=p["release_ms"], slow_release_ms=p.get("slow_release_ms"),
                max_reduction_db=p.get("max_reduction_db"), hold=hold if p.get("tail_safe") else None)
            _record_gain(t, gr)
            t.applied = t.measured["reduction_max_db"] >= IDLE_DB
            if t.applied:
                y = dsp._apply_gain(y, dsp._to_samples(gr, size, y.shape[0]))
        elif t.kind == "makeup":
            before, after = integrated_loudness(x, fs), integrated_loudness(y, fs)
            change = before - after if math.isfinite(before) and math.isfinite(after) else 0.0
            t.params = {"gain_db": change}
            t.label = f"Gain de compensation {change:+.1f} dB"
            t.applied = abs(change) >= 0.05
            if t.applied:
                y = y * 10 ** (change / 20)
        elif t.kind == "parallel":
            threshold = _sung_percentile(y, fs, p["percentile"]) - p["below_db"]
            y = dsp.parallel_compress(y, fs, threshold, p["blend"],
                                      low_hz=p.get("low_hz", 100.0), high_hz=p.get("high_hz", 5000.0))
        elif t.kind == "saturation":
            band, rest = dsp.split_band(y, fs, p.get("low_hz", 200.0), p.get("high_hz", 8000.0))
            # the drive acts on the band scaled to its own loud peaks, so the colour does not
            # depend on how loud the voice was rendered
            reference = 10 ** (_sung_percentile(band, fs, 99.0) / 20) * math.sqrt(2)
            if reference > 0:
                y = rest + reference * saturate(band / reference, fs, p["drive"], p["mix"], p.get("asymmetry", 0.0))
        elif t.kind == "gain":
            y = y * 10 ** (p["gain_db"] / 20)
        else:
            raise ValueError(f"traitement inconnu : {t.kind}")
    return y
