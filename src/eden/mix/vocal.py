"""One voice through a rap mix engineer's chain, decided from measurements.

Order of the chain (the one documented hip-hop sessions share, see
docs/mixage.md): pitch correction is already printed by FL Studio, then
high-pass → fixed resonances → low-mid build-up → light de-esser →
leveling compressor → peak compressor → parallel compression → saturation
→ presence / air → main de-esser. Each step has a measured trigger and a
cap; a step whose trigger is not met is simply not added.

When the voice is processed from FL's dry render, the user's reverbs and
delays are added back afterwards, untouched. When no dry render exists but
the FL chain holds a reverb or a delay, the compressors work "tail-safe":
little reduction, and a gain that never comes back above the phrase's mean
reduction and is frozen there in the gaps, so make-up gives the tails the
artist set about what it gives the voice (see ``dsp._smooth``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from eden.mix import dsp
from eden.mix.analysis import LOW_MID_MIN_DB, LOW_MID_STEADY_SHARE, VocalMeasure, deess_band_low_hz
from eden.mix.riding import felt_quarter, phrases_of
from eden.mix.treatments import Treatment

LEAD_ROLES = {"lead_vocal", "vocal"}


@dataclass(frozen=True)
class RoleProfile:
    highpass_hz: float
    deess_first_db: float  # light pass before compression (strongest 's' only)
    deess_main_db: float  # main pass at the end of the chain
    parallel_blend: float  # New York compression return (linear, relative to dry)
    saturation_mix: float
    push_back_db: float  # high shelf above 7 kHz: 0 for the lead, negative to sit behind it


PROFILES = {
    "lead_vocal": RoleProfile(80.0, 3.0, 6.0, 0.2, 0.15, 0.0),
    "vocal": RoleProfile(80.0, 3.0, 6.0, 0.2, 0.15, 0.0),
    "double": RoleProfile(130.0, 3.0, 8.0, 0.0, 0.1, -1.5),
    "back_vocal": RoleProfile(160.0, 3.0, 8.0, 0.0, 0.1, -2.0),
    "adlib": RoleProfile(130.0, 3.0, 8.0, 0.1, 0.2, -1.5),
}
TAIL_SAFE_MAX_REDUCTION_DB = 3.0
HIGHPASS_TRIGGER_DB = -32.0  # energy an octave under the planned cut, re. the whole voice (Eden's choice)
HIGHPASS_REST_TRIGGER_DB = -40.0  # power under the planned cut in the rests, re. the sung voice (Eden's choice)


def tail_hold(m: VocalMeasure, x: np.ndarray, fs: float, tempo_bpm: float | None = None) -> np.ndarray:
    """1 ms frames of the rests between phrases (only an effect tail can sound there): the
    compressors freeze their gain over them. Phrases are found on an envelope smoothed like a
    loudness meter (22 ms attack, 50 ms release) and split by rests of a 16th note or more."""
    level, _ = dsp.band_levels_db(x, fs)
    if level.size == 0:
        return np.zeros(0, dtype=bool)
    power = 10 ** (level / 10)
    up, down = math.exp(-1 / 22), math.exp(-1 / 50)
    smooth = np.empty_like(power)
    state = 0.0
    for i, v in enumerate(power):  # 1 ms frames
        coef = up if v > state else down
        state = coef * state + (1 - coef) * v
        smooth[i] = state
    sung = 10 * np.log10(np.maximum(smooth, 1e-20)) > m.sung_p70_db - 20.0
    gap = int(felt_quarter(tempo_bpm) / 4 / dsp.FRAME_S) if tempo_bpm else 150
    hold = np.ones(level.size, dtype=bool)
    for start, end in phrases_of(sung, gap):
        hold[start:end] = False
    return hold


def plan_voice(m: VocalMeasure, role: str, k: float, fl_space_untracked: bool) -> list[Treatment]:
    """Corrective and shaping chain of one voice (level changes are decided elsewhere).

    ``fl_space_untracked``: the FL chain holds a reverb or delay that could
    not be rendered apart (tail-safe compression, see module docstring:
    ``apply`` then gets the frames to hold from ``tail_hold``).
    """
    if k <= 0 or not math.isfinite(m.loudness_lufs):
        return []
    profile = PROFILES.get(role, PROFILES["vocal"])
    out: list[Treatment] = []

    # 1. high-pass: never above the lowest sustained note of the voice, and only when something sounds
    #    under the planned cut. While the voice sings, it is read an octave under the cut, where the
    #    filter takes 12 dB or more (rumble, plosives): just under the cut the voice itself still
    #    sounds (notes below its 5th percentile, the syllables' onsets around its fundamental). In the
    #    rests between phrases the voice is silent, so whatever sounds under the cut is noise (rumble,
    #    handling): read up to the cut, it catches a rumble too weak to stand out of the voice's own
    #    attacks while it sings
    hp = profile.highpass_hz
    if m.lowest_f0_hz:
        hp = min(hp, 0.9 * m.lowest_f0_hz)
    sung_lows, rest_lows = m.energy_below_db(hp / 2), m.rest_energy_below_db(hp)
    found = []
    if sung_lows > HIGHPASS_TRIGGER_DB:
        found.append(f"grondement ou plosives pendant le chant : {sung_lows:.0f} dB de l'énergie de la voix "
                     f"sous {hp / 2:.0f} Hz (une octave sous {hp:.0f} Hz, la coupe à 100 %)")
    if rest_lows > HIGHPASS_REST_TRIGGER_DB:
        found.append(f"bruit grave dans les silences entre les phrases (grondement, manipulation du micro) : "
                     f"{rest_lows:.0f} dB sous {hp:.0f} Hz (la coupe à 100 %) par rapport à la voix chantée")
    if found:
        freq = max(20.0, hp * k)
        if m.lowest_f0_hz:
            found.append(f"note la plus grave {m.lowest_f0_hz:.0f} Hz")
        reason = " ; ".join(found)
        out.append(Treatment("highpass", f"Coupe-bas {freq:.0f} Hz", reason[0].upper() + reason[1:],
                             {"freq_hz": freq, "q": 0.7071}))

    # 2. fixed resonances (room, microphone)
    for r in m.resonances:
        cut = -min(4.0, 0.6 * (r.excess_db - 2.0))
        out.append(Treatment(
            "eq", f"Résonance {r.freq_hz:.0f} Hz {cut * k:.1f} dB",
            f"Pic étroit {r.excess_db:.1f} dB au-dessus du spectre voisin",
            {"freq_hz": r.freq_hz, "q": 6.0, "gain_db": cut * k}))

    # 3. low-mid build-up (proximity effect, boxiness): only a real bump of the voice's harmonics, seen
    #    on two sung notes at least (see ``analysis.low_mid_buildup``), not a general tilt (blind low-mid
    #    cuts are not supported by expert practice), and not where a resonance cut already acts
    cut_there = any(abs(math.log2(r.freq_hz / m.low_mid_hz)) <= 1 / 3 for r in m.resonances)
    if m.mud_db > 6.0 and m.low_mid_excess_db >= LOW_MID_MIN_DB and not cut_there:
        cut = -min(4.0, 1.0 + 0.75 * m.low_mid_excess_db)
        out.append(Treatment(
            "eq", f"Bas-médiums {m.low_mid_hz:.0f} Hz {cut * k:.1f} dB",
            f"Bosse de {m.low_mid_excess_db:.1f} dB à {m.low_mid_hz:.0f} Hz : sur un tiers d'octave, les "
            "harmoniques de la voix dépassent d'autant la droite de leurs voisines (±1 octave) ; "
            f"{m.low_mid_notes} notes chantées la portent chacune (au moins {LOW_MID_MIN_DB - 1:.1f} dB, "
            f"au-dessus de la droite dans {LOW_MID_STEADY_SHARE * 100:.0f} % des cas ou plus) ; "
            f"bas-médiums {min(m.mud_db, 30.0):.0f} dB{'+' if m.mud_db > 30 else ''} au-dessus de la présence",
            {"freq_hz": m.low_mid_hz, "q": 1.2, "gain_db": cut * k}))

    # 4. light de-esser before compression, on the strongest 's' only (louder than the vowels − 2 dB);
    #    both de-essers set their threshold on the vowels of the signal they receive, and the 's' are
    #    measured in their band: the level the de-essers compare with that threshold
    deess_low = deess_band_low_hz(m.sibilant_peak_hz)
    where = (f" ; ils culminent vers {m.sibilant_peak_hz:.0f} Hz, bande dès {deess_low / 1000:.1f} kHz"
             if m.sibilant_peak_hz else " ; pic des « s » non mesuré, bande dès 4,5 kHz")
    if m.sibilant_excess_db > -1.0:
        out.append(Treatment(
            "deesser", f"De-esser léger (max {profile.deess_first_db * k:.0f} dB)",
            f"Dans la bande du de-esser, les « s » les plus forts montent à {m.sibilant_excess_db:+.1f} dB "
            f"par rapport aux voyelles{where}",
            {"below_vowels_db": 2.0, "max_reduction_db": profile.deess_first_db * k, "low_hz": deess_low}))

    # 5. leveling compressor (slow, low ratio, program-dependent release) then 6. peak compressor
    cap = TAIL_SAFE_MAX_REDUCTION_DB if fl_space_untracked else None
    # thresholds are set when the stage runs, on the level it really receives: the loudest 10 %
    # (leveling) or 3 % (peaks) of the sung moments get ``reduction_db``, which scales with k
    if m.dynamic_spread_db > 4.0:
        ratio = 1 + (min(3.0, 2.0 + (m.dynamic_spread_db - 6.0) / 4) - 1) * k
        out.append(Treatment(
            "compressor", f"Compression de niveau {ratio:.1f}:1",
            f"Écart de {m.dynamic_spread_db:.1f} dB entre passages faibles et forts"
            + (" ; réduction limitée, la voix porte déjà une reverb ou un delay FL" if fl_space_untracked else ""),
            {"percentile": 90.0, "reduction_db": 3.0 * k, "ratio": ratio, "attack_ms": 10.0,
             "release_ms": 60.0, "slow_release_ms": 800.0,
             "max_reduction_db": cap * k if cap else None, "tail_safe": fl_space_untracked}))
    if m.crest_db > 9.0:
        ratio = 1 + 3.0 * k
        out.append(Treatment(
            "compressor", f"Compression des crêtes {ratio:.1f}:1",
            f"Facteur de crête {m.crest_db:.0f} dB : les consonnes et attaques dépassent le corps de la voix",
            {"percentile": 97.0, "reduction_db": 3.0 * k, "ratio": ratio, "attack_ms": 2.0,
             "release_ms": 80.0, "max_reduction_db": (cap if cap else 6.0) * k, "tail_safe": fl_space_untracked}))

    # 7. parallel (New York) compression: density and body without flattening the attacks, for a
    #    voice whose words stay far above their own body (peaky after the serial stages)
    if profile.parallel_blend > 0 and not fl_space_untracked and m.crest_db > 12.0:
        out.append(Treatment(
            "parallel", f"Compression parallèle ({profile.parallel_blend * k * 100:.0f} %)",
            f"Facteur de crête {m.crest_db:.0f} dB : une copie très compressée (8:1), limitée à 100 Hz – 5 kHz, "
            "mélangée sous la voix la rend plus dense sans écraser les attaques",
            {"percentile": 70.0, "below_db": 12.0, "blend": profile.parallel_blend * k}))

    # 8. saturation: harmonics in the body of the voice, up to where the 's' start
    if profile.saturation_mix > 0:
        out.append(Treatment(
            "saturation", f"Saturation douce ({profile.saturation_mix * k * 100:.0f} %)",
            f"Pratique des voix rap : harmoniques ajoutées entre 200 Hz et {deess_low / 1000:.1f} kHz "
            "(suréchantillonné ×4), même couleur quel que soit le volume de la voix : elle ressort sur les "
            "petites enceintes",
            {"drive": 2.0, "mix": profile.saturation_mix * k, "asymmetry": 0.1, "high_hz": deess_low}))

    # 9. air (only when the top end is dull on the vowels) and the push-back of secondary voices
    if math.isfinite(m.air_db) and m.air_db < -25.0:
        out.append(Treatment(
            "shelf", f"Air +{1.5 * k:.1f} dB au-dessus de 10 kHz",
            f"Voyelles ternes : {m.air_db:.0f} dB au-dessus de 8 kHz par rapport à 2–5 kHz",
            {"freq_hz": 10000.0, "gain_db": 1.5 * k, "high": True}))
    if profile.push_back_db:
        out.append(Treatment(
            "shelf", f"Recul {profile.push_back_db * k:.1f} dB au-dessus de 7 kHz",
            "Voix secondaire : moins brillante que la voix principale pour se placer derrière elle",
            {"freq_hz": 7000.0, "gain_db": profile.push_back_db * k, "high": True}))

    # 10. main de-esser, after compression and saturation have raised the 's' (those above vowels − 6 dB)
    if m.sibilant_excess_db > -5.0:
        depth = min(profile.deess_main_db, max(2.0, m.sibilant_excess_db + 6.0))
        out.append(Treatment(
            "deesser", f"De-esser principal (max {depth * k:.1f} dB)",
            f"Dans la bande du de-esser, les « s » montent à {m.sibilant_excess_db:+.1f} dB par rapport aux "
            f"voyelles ({m.sibilant_share * 100:.1f} % du chant){where}",
            {"below_vowels_db": 6.0, "max_reduction_db": depth * k, "low_hz": deess_low}))

    # 11. make-up: the compressors and de-essers took level; it is given back, so the balance of the
    #     voice in the mix is decided on a measurement, in one place, and explained there
    if any(t.kind in ("compressor", "deesser") for t in out):
        out.append(Treatment(
            "makeup", "Gain de compensation",
            "Rend à la voix le volume que la compression lui a pris ; son niveau dans le mix est réglé "
            "ensuite, sur une mesure"))
    return out
