"""Eden's mix: explicit rules on measurements, applied on FL Studio's renders.

Parts of the mix (all rendered by FL Studio, Master effects bypassed):
  * each voice alone, with its whole FL chain (inserts, buses, sends);
  * the rest = pre-master mix − sum of the voices (instru, other sources and
    whatever the buses add).
At intensity 0 nothing is changed, so the parts add up exactly to the
original pre-master mix. Every change Eden makes is recorded with the
measurement that triggered it.

The numeric targets below are starting values for rap vocals; they are
meant to be refined with listening tests (docs/02-plan-developpement.md).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from eden.mix import dsp
from eden.mix.analysis import VocalMeasure, balance_against, measure_vocal, presence_masking_db
from eden.mix.loudness import integrated_loudness

LEAD_ROLES = {"lead_vocal", "vocal"}
# role -> (target, lowest acceptable, highest acceptable) in dB
LEAD_BALANCE = (1.5, -0.5, 4.0)  # lead voice vs. the instru while it sings
RELATIVE_TO_LEAD = {
    "back_vocal": (-7.0, -10.0, -4.0),
    "adlib": (-6.0, -9.0, -3.0),
    "double": (-6.0, -9.0, -3.0),
}
MAX_LEVEL_CHANGE_DB = 4.0
SIBILANT_LIMIT_DB = -3.0  # 's' sounds this close to the vowels' level are piercing
HIGHPASS_HZ = {"lead_vocal": 80.0, "vocal": 80.0, "double": 110.0, "back_vocal": 120.0, "adlib": 110.0}


@dataclass
class Treatment:
    kind: str  # highpass | eq_cut | compressor | deesser | gain | presence_dip
    label: str  # short French description shown to the user
    reason: str  # measurement that triggered it
    params: dict = field(default_factory=dict)


@dataclass
class Part:
    key: str  # "ch<index>" for a voice, "rest" for everything else
    label: str
    role: str
    audio: np.ndarray = field(repr=False)


@dataclass
class PartResult:
    key: str
    label: str
    role: str
    treatments: list[Treatment]
    loudness_before: float
    loudness_after: float


@dataclass
class MixOutcome:
    premaster: np.ndarray = field(repr=False)
    sample_rate: int
    intensity: float
    parts: list[PartResult]
    staging_gain_db: float  # keeps the level entering the FL Master as before
    loudness_original: float
    loudness_mix: float


def plan_vocal(m: VocalMeasure, role: str, k: float) -> list[Treatment]:
    """Corrective processing of one voice, from its measurements (before level)."""
    if k <= 0 or not math.isfinite(m.loudness_lufs):
        return []
    out: list[Treatment] = []

    hp = HIGHPASS_HZ.get(role, 80.0)
    lows = m.low_energy_db if role in LEAD_ROLES else m.low_120_db
    if lows > -25.0:
        out.append(Treatment(
            "highpass", f"Coupe-bas {hp * k:.0f} Hz",
            f"Grondement ou plosives sous {70 if role in LEAD_ROLES else 120} Hz "
            f"({lows:.0f} dB de l'énergie de la voix)",
            {"freq_hz": max(20.0, hp * k), "q": 0.7071}))

    for r in m.resonances:
        cut = -min(3.0, 0.6 * (r.excess_db - 2.0))
        out.append(Treatment(
            "eq_cut", f"Résonance {r.freq_hz:.0f} Hz {cut * k:.1f} dB",
            f"Pic étroit {r.excess_db:.1f} dB au-dessus du spectre voisin",
            {"freq_hz": r.freq_hz, "q": 6.0, "gain_db": cut * k}))

    if m.mud_db > 6.0:
        cut = -min(3.0, 1.5 + (m.mud_db - 6.0) / 2)
        out.append(Treatment(
            "eq_cut", f"Bas-médiums 300 Hz {cut * k:.1f} dB",
            f"Bas-médiums {min(m.mud_db, 30.0):.0f} dB{'+' if m.mud_db > 30 else ''} au-dessus "
            "de la présence (son terne)",
            {"freq_hz": 300.0, "q": 1.0, "gain_db": cut * k}))

    if m.sibilant_excess_db > SIBILANT_LIMIT_DB:
        depth = min(8.0, m.sibilant_excess_db + 6.0)
        out.append(Treatment(
            "deesser", f"De-esser jusqu'à {depth * k:.1f} dB",
            f"Les « s » montent à {m.sibilant_excess_db:+.1f} dB par rapport aux voyelles "
            f"({m.sibilant_share * 100:.1f} % du chant)",
            {"threshold_db": m.vowel_level_db - 6.0, "max_reduction_db": depth * k}))

    if m.dynamic_spread_db > 7.0 and m.crest_db > 10.0:
        ratio = min(4.0, max(1.5, 1 + (m.dynamic_spread_db - 5.0) / 3))
        eff = 1 + (ratio - 1) * k
        out.append(Treatment(
            "compressor", f"Compression {eff:.1f}:1",
            f"Écart de niveau de {m.dynamic_spread_db:.1f} dB entre passages faibles et forts "
            f"(facteur de crête {m.crest_db:.0f} dB)",
            {"threshold_db": m.detector_p70_db, "ratio": eff, "attack_ms": 8.0, "release_ms": 140.0}))
    return out


def apply(x: np.ndarray, fs: float, treatments: list[Treatment]) -> np.ndarray:
    y = x
    for t in treatments:
        p = t.params
        if t.kind == "highpass":
            y = dsp.apply_sos(y, dsp.highpass_sos(fs, p["freq_hz"], p["q"]))
        elif t.kind == "eq_cut":
            y = dsp.apply_sos(y, dsp.peaking_sos(fs, p["freq_hz"], p["q"], p["gain_db"]))
        elif t.kind == "deesser":
            y = dsp.deess(y, fs, p["threshold_db"], p["max_reduction_db"])
        elif t.kind == "compressor":
            y = dsp.compress(y, fs, p["threshold_db"], p["ratio"],
                             attack_ms=p["attack_ms"], release_ms=p["release_ms"])
        elif t.kind == "gain":
            y = y * 10 ** (p["gain_db"] / 20)
        else:
            raise ValueError(f"traitement inconnu : {t.kind}")
    return y


def _level_change(current: float, target: tuple[float, float, float], k: float) -> float:
    goal, low, high = target
    if low <= current <= high or not math.isfinite(current):
        return 0.0
    return max(-MAX_LEVEL_CHANGE_DB, min(MAX_LEVEL_CHANGE_DB, goal - current)) * k


def mix(voices: list[Part], rest: Part, fs: int, intensity: float, premaster_lufs: float
        ) -> MixOutcome:
    """Process every voice, balance it, carve room in the instru, keep the Master input level."""
    k = max(0.0, min(1.0, intensity))
    processed: dict[str, np.ndarray] = {}
    results: dict[str, PartResult] = {}
    measures: dict[str, VocalMeasure] = {}

    for v in voices:
        m = measure_vocal(v.audio, fs)
        treatments = plan_vocal(m, v.role, k)
        processed[v.key] = apply(v.audio, fs, treatments)
        measures[v.key] = measure_vocal(processed[v.key], fs) if treatments else m
        results[v.key] = PartResult(v.key, v.label, v.role, treatments, m.loudness_lufs,
                                    measures[v.key].loudness_lufs)

    # Levels: the lead voices against the instru first, then the others against
    # the loudest lead *after* its own change.
    leads = [v for v in voices if v.role in LEAD_ROLES and math.isfinite(measures[v.key].loudness_lufs)]

    def change_level(v: Part, change: float, what: str) -> None:
        if abs(change) < 0.1:
            return
        t = Treatment("gain", f"Niveau {change:+.1f} dB", f"Équilibre : {what}", {"gain_db": change})
        processed[v.key] = apply(processed[v.key], fs, [t])
        results[v.key].treatments.append(t)
        results[v.key].loudness_after += change

    if k > 0:
        for v in leads:
            current = balance_against(measures[v.key], rest.audio, fs)
            change_level(v, _level_change(current, LEAD_BALANCE, k),
                         f"voix {current:+.1f} dB par rapport à l'instru pendant qu'elle chante")
        reference = max(leads, key=lambda v: results[v.key].loudness_after, default=None)
        for v in voices:
            if v.role not in RELATIVE_TO_LEAD or reference is None:
                continue
            if not math.isfinite(results[v.key].loudness_after):
                continue
            current = results[v.key].loudness_after - results[reference.key].loudness_after
            change_level(v, _level_change(current, RELATIVE_TO_LEAD[v.role], k),
                         f"{current:+.1f} dB par rapport à « {reference.label} »")

    # Room for the lead voices in the instru's presence band, only while they sing.
    rest_out = rest.audio
    rest_treatments: list[Treatment] = []
    if k > 0 and leads:
        lead_mix = sum(processed[v.key] for v in leads)
        lead_m = measure_vocal(lead_mix, fs)
        masking = presence_masking_db(lead_mix, rest.audio, fs, lead_m.active_blocks)
        if masking > -3.0:
            depth = min(3.0, 1.0 + (masking + 3.0) / 3.0)
            level, _ = dsp.band_levels_db(lead_mix, fs)
            env, size = dsp.activity_envelope(lead_mix, fs, float(np.percentile(level, 95)) - 35.0)
            t = Treatment(
                "presence_dip", f"Place pour la voix : instru −{depth * k:.1f} dB vers 1,5–4 kHz",
                f"L'instru est {masking:+.1f} dB par rapport à la voix dans la zone qui rend "
                "les paroles intelligibles, pendant le chant",
                {"depth_db": depth * k})
            rest_out = dsp.dip_band_when(rest.audio, fs, env, size, depth * k)
            rest_treatments.append(t)
    rest_lufs = integrated_loudness(rest.audio, fs)
    results[rest.key] = PartResult(rest.key, rest.label, rest.role, rest_treatments, rest_lufs,
                                   integrated_loudness(rest_out, fs) if rest_treatments else rest_lufs)

    out = rest_out + sum(processed.values()) if processed else rest_out.copy()
    mix_lufs = integrated_loudness(out, fs)
    staging = 0.0
    if math.isfinite(mix_lufs) and math.isfinite(premaster_lufs) and abs(premaster_lufs - mix_lufs) >= 0.01:
        staging = premaster_lufs - mix_lufs
        out = out * 10 ** (staging / 20)
    return MixOutcome(out, fs, k, [*(results[v.key] for v in voices), results[rest.key]],
                      staging, premaster_lufs, integrated_loudness(out, fs))
