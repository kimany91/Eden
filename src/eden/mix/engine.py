"""Eden's mix: what a rap mix engineer does, decided from measurements.

Everything is done on FL Studio's own renders (parts, see ``parts.py``):

1. the song: key (harmonic parts, the 808 settling relative keys, the
   beat's own tuning), tempo (from the project), the 808's notes against
   the key, kick / 808 collisions, stereo of the low end;
2. the lead voices' chains (``vocal.py``), on FL's dry render when the voice
   carries FL reverbs or delays, which are then put back untouched;
3. the beat: room for the words (the bands that cover the lead most,
   weighted by their importance for intelligibility, dip while it sings),
   kick / 808 duck when they collide and nothing ducks already, harmonics
   for small speakers when the 808 is a bare sine. This comes before the
   balance, so the balance is measured on the beat as it will be heard;
4. the leads: level against the beat while they sing, riding phrase by
   phrase (``riding.py``), space when they have none (``space.py``);
5. the other voices one by one: chain, level against the lead (copies of
   the lead are never raised: comb filtering), placement (``stereo.py``),
   a dip in 1–4 kHz while the lead sings, space when they have none;
6. the reverb of the whole mix (the user's FL effects and Eden's) is kept
   under a ceiling; the mix goes back to the level it came in at.

Voices are processed one at a time and added up as they are done, so
memory does not grow with the number of voices. At intensity 0 nothing is
changed: the result is the original pre-master mix, bit for bit. Every
change is recorded with its reason.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from eden.mix import dsp, lowend, stereo
from eden.mix.analysis import Level, balance_against, band_masking, level_of, measure_vocal
from eden.mix.loudness import integrated_loudness
from eden.mix.parts import Part, Parts
from eden.mix.riding import EXPOSED_DB, MASKING_FROM_HZ, TOLERANCE_DB, apply_ride, felt_quarter, ride
from eden.mix.space import design_space, render_space, returns_scale
from eden.mix.tonality import bass_pitch_classes, detect_key, tuning
from eden.mix.treatments import Treatment, apply
from eden.mix.vocal import LEAD_ROLES, plan_voice, tail_hold

# role -> (target, lowest acceptable, highest acceptable) in dB
# Lead vs. the beat while it sings: Eden's choice. Measured mixes put the lead around 0 dB against
# everything else (beat and other voices); the other voices are set ~6 dB under the lead afterwards,
# so +1 dB against the beat lands near that. −1 to +4 dB is accepted as it is.
LEAD_BALANCE = (1.0, -1.0, 4.0)
RELATIVE_TO_LEAD = {
    "back_vocal": (-7.0, -10.0, -4.0),
    "adlib": (-6.0, -9.0, -3.0),
    "double": (-6.0, -10.0, -3.0),
}
MAX_LEVEL_CHANGE_DB = 4.0
MAX_CARVE_DB = 3.0  # dip of the beat in one band while the lead sings
SECONDARY_DIP_DB = 2.0  # backs / ad-libs in 1–4 kHz while the lead sings
MAX_REVERB_LU = -16.0  # relative reverb loudness of the whole mix (−9 LU: too wet; −14 LU: optimum; rap is drier)
HARMONICS_NEEDED_DB = -20.0  # an 808 whose harmonics are this far under its fundamental is a bare sine

ProgressCallback = Callable[[str], None]


@dataclass
class PartResult:
    key: str
    label: str
    role: str
    treatments: list[Treatment]
    loudness_before: float
    loudness_after: float
    fl_space: str = "none"  # none | tracked (rendered apart, put back untouched) | untracked
    level_change_db: float = 0.0
    placement: str | None = None
    space: list[str] = field(default_factory=list)
    ride: dict = field(default_factory=dict)


@dataclass
class SongAnalysis:
    key: str | None
    key_confidence: str | None
    tuning_cents: float  # the beat's tuning relative to A = 440 Hz
    tempo_bpm: float | None
    felt_quarter_ms: float
    bass_root: str | None
    bass_out_of_scale: list[str]
    bass_detune_cents: float | None
    kick_overlap: float
    low_correlation: float
    harmonics_db: float


@dataclass
class MixOutcome:
    premaster: np.ndarray = field(repr=False)
    sample_rate: int
    intensity: float
    parts: list[PartResult]
    song: SongAnalysis
    staging_gain_db: float  # keeps the level entering the master as before
    loudness_original: float
    loudness_mix: float
    reverb_lu: float  # relative reverb loudness of the whole mix (De Man et al. 2017)
    warnings: list[str] = field(default_factory=list)


def _level_change(current: float, target: tuple[float, float, float], k: float) -> float:
    goal, low, high = target
    if low <= current <= high or not math.isfinite(current):
        return 0.0
    return max(-MAX_LEVEL_CHANGE_DB, min(MAX_LEVEL_CHANGE_DB, goal - current)) * k


def _gain(x: np.ndarray, db: float) -> np.ndarray:
    return x * 10 ** (db / 20)


HARMONIC_ROLES = {"music", "fx", "unknown"}  # groups that carry the chords (no drums, no 808)
HARMONY_FMIN_HZ = 200.0


def analyse_song(parts: Parts, tempo_bpm: float | None) -> tuple[SongAnalysis, lowend.LowEndReport]:
    """Key from the harmonic parts (drums and 808 left out: their noise and partials blur the
    chroma), tonic settled by the 808, tuning of the beat, low end."""
    fs = parts.sample_rate
    context = parts.residual.audio + sum((g.audio for g in parts.groups), np.zeros_like(parts.residual.audio))
    bass = next((g for g in parts.groups if g.role == "bass"), None)
    drums = next((g for g in parts.groups if g.role == "drums"), None)
    harmonic = [g for g in parts.groups if g.role in HARMONIC_ROLES]
    harmony = (parts.residual.audio + sum((g.audio for g in harmonic), np.zeros_like(parts.residual.audio))
               if harmonic else context)
    cents = tuning(harmony, fs)
    bass_chroma = bass_pitch_classes(bass.audio if bass else context, fs, cents)
    # chords read above 200 Hz: below, kick, 808 and bass lines blur the chroma (Faraldo et al.);
    # the bass notes are given apart, to settle the tonic
    key = detect_key(harmony, fs, bass_chroma, fmin=HARMONY_FMIN_HZ, tuning_cents=cents)
    low = lowend.analyse(bass.audio if bass else None, drums.audio if drums else None, context, fs,
                         key.scale if key else None, cents)
    song = SongAnalysis(key.display if key else None, key.confidence if key else None, cents, tempo_bpm,
                        felt_quarter(tempo_bpm) * 1000 if tempo_bpm else 500.0, low.root_name,
                        low.out_of_scale, low.detune_cents, low.kick_overlap, low.low_correlation,
                        low.harmonics_db)
    return song, low


def _chain(v: Part, fs: float, k: float, status: str, tempo_bpm: float | None
           ) -> tuple[np.ndarray, np.ndarray | None, Level, PartResult]:
    """One voice through its chain: (processed voice, its FL reverbs/delays part, level, result).
    Only the steps that changed something are reported."""
    source = v.dry if v.dry is not None else v.audio
    m = measure_vocal(source, fs)
    treatments = plan_voice(m, v.role, k, status == "untracked")
    hold = tail_hold(m, source, fs, tempo_bpm) if status == "untracked" else None
    processed = apply(source, fs, treatments, hold=hold) if treatments else source
    treatments = [t for t in treatments if t.applied]
    fl_wet = None
    if v.dry is not None:
        fl_wet = v.space
        processed = processed + fl_wet  # the user's FL reverbs and delays, untouched
    level = level_of(processed, fs) if treatments else Level(m.loudness_lufs, m.active_blocks)
    return processed, fl_wet, level, PartResult(v.key, v.label, v.role, treatments, m.loudness_lufs,
                                                level.lufs, status)


def _untouched(parts: Parts, fs: float, fl_space: dict[str, str]) -> list[PartResult]:
    out = []
    for p in [*parts.voices, *parts.groups]:
        lufs = integrated_loudness(p.audio, fs)
        out.append(PartResult(p.key, p.label, p.role, [], lufs, lufs, fl_space.get(p.key, "none")))
    return out


def mix(parts: Parts, intensity: float, tempo_bpm: float | None, fl_space: dict[str, str],
        progress: ProgressCallback | None = None) -> MixOutcome:
    """Mix the parts; ``fl_space[voice key]`` says whether FL reverbs/delays are none/tracked/untracked."""
    fs = parts.sample_rate
    k = max(0.0, min(1.0, intensity))
    premaster_lufs = integrated_loudness(parts.premaster, fs)
    warnings: list[str] = []

    def say(text: str) -> None:
        if progress:
            progress(text)

    say("Analyse du morceau")
    song, low = analyse_song(parts, tempo_bpm)
    if song.bass_out_of_scale and song.key:
        warnings.append(f"Le 808 joue {', '.join(song.bass_out_of_scale)} alors que le morceau est en "
                        f"{song.key} : à vérifier dans le projet (Eden ne retouche pas les notes)")
    if song.bass_detune_cents is not None and song.bass_detune_cents > 25:
        warnings.append(f"Le 808 est désaccordé d'environ {song.bass_detune_cents:.0f} cents par rapport "
                        "au reste de l'instru")
    if k <= 0:  # bit-exact: nothing is changed
        return MixOutcome(parts.premaster.copy(), fs, k, _untouched(parts, fs, fl_space), song, 0.0,
                          premaster_lufs, premaster_lufs, -math.inf, warnings)

    results: dict[str, PartResult] = {}
    leads = [v for v in parts.voices if v.role in LEAD_ROLES]
    others = [v for v in parts.voices if v.role not in LEAD_ROLES]

    # -- 1. the leads' chains ------------------------------------------------------------
    chained = {}
    for v in leads:
        say(f"Voix : {v.label}")
        chained[v.key] = _chain(v, fs, k, fl_space.get(v.key, "none"), tempo_bpm)
        results[v.key] = chained[v.key][3]
    sung = [v for v in leads if math.isfinite(chained[v.key][2].lufs)]
    lead_mix = sum((chained[v.key][0] for v in sung), np.zeros(parts.premaster.shape)) if sung else None

    # -- 2. the beat: the low end, then room for the words -----------------------------------
    for g in parts.groups:
        lufs = integrated_loudness(g.audio, fs)
        results[g.key] = PartResult(g.key, g.label, g.role, [], lufs, lufs, "none")
    groups = np.zeros(parts.premaster.shape)
    bass = next((g for g in parts.groups if g.role == "bass"), None)
    drums = next((g for g in parts.groups if g.role == "drums"), None)
    for g in parts.groups:
        if g is not bass:
            groups += g.audio
    if bass is not None:
        say("Basses et 808")
        audio = bass.audio
        res = results[bass.key]
        if drums is not None and low.kick_overlap > 0.5 and low.existing_duck_db < 2.0:
            _, _, hits = lowend.kick_808_interaction(bass.audio, drums.audio, fs)
            audio = lowend.duck_low_band(audio, fs, hits, lowend.MAX_DUCK_DB * k)
            res.treatments.append(Treatment(
                "duck", f"808 baissé de {lowend.MAX_DUCK_DB * k:.0f} dB sous {lowend.CROSSOVER_HZ:.0f} Hz à chaque kick",
                f"{low.kick_overlap * 100:.0f} % des kicks tombent sur une note de 808 qui ne baisse pas "
                f"({low.existing_duck_db:.1f} dB) : les deux se marchent dessus dans le sub"))
        if math.isfinite(low.harmonics_db) and low.harmonics_db < HARMONICS_NEEDED_DB:
            audio = lowend.add_harmonics(audio, fs, k=k)
            res.treatments.append(Treatment(
                "harmonics", "Harmoniques ajoutées au 808",
                f"Harmoniques à {low.harmonics_db:.0f} dB sous la fondamentale : un 808 presque sinusoïdal "
                "disparaît sur les petites enceintes ; ses harmoniques y laissent entendre la note"))
        if res.treatments:
            res.loudness_after = integrated_loudness(audio, fs)
        groups += audio
        del audio
    say("Place pour les paroles dans l'instru")
    env = size = None
    if lead_mix is not None:
        level, _ = dsp.band_levels_db(lead_mix, fs)
        env, size = dsp.activity_envelope(lead_mix, fs, float(np.percentile(level, 95)) - 35.0,
                                          attack_ms=15.0, release_ms=200.0)
        bands = band_masking(lead_mix, parts.residual.audio + groups, fs, level_of(lead_mix, fs).active_blocks)
        chosen = sorted((b for b in bands if b.masking_db > -3.0),
                        key=lambda b: b.weight * (b.masking_db + 3.0), reverse=True)[:3]
        depths = [min(MAX_CARVE_DB, 1.0 + (b.masking_db + 3.0) / 3.0) * k for b in chosen]
        # the dips are linear: carving the sum of the groups is carving each of them
        for b, depth in zip(chosen, depths, strict=True):
            groups = dsp.dip_band_when(groups, fs, env, size, depth, b.low_hz, b.high_hz)
        if chosen:
            carve = Treatment(
                "carve", "Place pour la voix : " + ", ".join(
                    f"{b.low_hz:.0f}–{b.high_hz:.0f} Hz −{d:.1f} dB" for b, d in zip(chosen, depths, strict=True)),
                "Bandes où l'instru couvre le plus la voix (pondérées par leur importance pour les paroles) : "
                + ", ".join(f"{b.masking_db:+.1f} dB" for b in chosen) + ", seulement pendant le chant")
            for g in parts.groups:
                results[g.key].treatments.insert(0, carve)
                results[g.key].loudness_after = math.nan  # carved inside the whole instru
        del lead_mix
    beat = parts.residual.audio + groups
    del groups

    shape = parts.premaster.shape
    voices_sum, returns_sum, fl_wet_sum = np.zeros(shape), np.zeros(shape), np.zeros(shape)

    def add_space(v: Part, audio: np.ndarray, position: float = 0.0) -> None:
        nonlocal returns_sum
        if fl_space.get(v.key, "none") != "none" or not math.isfinite(results[v.key].loudness_after):
            return
        say(f"Espace : {v.label}")
        plan = design_space(tempo_bpm, v.role, k)
        wet, report = render_space(audio, fs, plan, k)
        returns_sum += stereo.balance(wet, position) if position else wet
        results[v.key].space = report + plan.notes

    def set_level(v: Part, change: float, what: str) -> float:
        if abs(change) < 0.1:
            return 0.0
        results[v.key].treatments.append(Treatment("gain", f"Niveau {change:+.1f} dB", f"Équilibre : {what}",
                                                   {"gain_db": change}))
        results[v.key].loudness_after += change
        results[v.key].level_change_db = change
        return change

    # -- 3. the leads: balance against the beat, riding, space -----------------------------
    say("Équilibre et suivi de la voix principale")
    reference = None
    for v in leads:
        processed, fl_wet, level, _ = chained.pop(v.key)
        if math.isfinite(level.lufs):
            current = balance_against(level, beat, fs)
            gain = 10 ** (set_level(v, _level_change(current, LEAD_BALANCE, k),
                                    f"voix {current:+.1f} dB par rapport à l'instru pendant qu'elle chante ; "
                                    f"visé {LEAD_BALANCE[0]:+.0f} dB, accepté de {LEAD_BALANCE[1]:+.0f} à "
                                    f"{LEAD_BALANCE[2]:+.0f} dB (mesure BS.1770, où une voix lit environ "
                                    "2 LU plus bas qu'à l'oreille)") / 20)
            processed = processed * gain
            fl_wet = fl_wet * gain if fl_wet is not None else None
            r = ride(processed, beat, fs, tempo_bpm, k)
            if r.moved:
                processed = apply_ride(processed, r)
                fl_wet = apply_ride(fl_wet, r) if fl_wet is not None else None
                results[v.key].ride = {"phrases": len(r.phrases), "moved": r.moved,
                                       "max_change_db": r.max_change_db}
                results[v.key].treatments.append(Treatment(
                    "ride", f"Niveau suivi sur {r.moved} phrase(s), jusqu'à {r.max_change_db:.1f} dB",
                    f"D'une phrase à l'autre, la voix doit rester à {r.reference_db:+.1f} dB de l'instru "
                    f"au-dessus de {MASKING_FROM_HZ:.0f} Hz, la bande qui couvre les paroles (son équilibre sur "
                    f"tout le morceau) ; écart toléré ±{TOLERANCE_DB:.1f} dB ; baissée seulement de ce que la voix "
                    "elle-même est montée, jamais parce que l'instru se retire"
                    + (f" ; {r.exposed} phrase(s) laissée(s) telle(s) quelle(s), l'instru y est à plus de "
                       f"{EXPOSED_DB:.0f} dB sous sa médiane" if r.exposed else "")))
            if reference is None or results[v.key].loudness_after > results[reference.key].loudness_after:
                reference = v
            add_space(v, processed)
        voices_sum += processed
        if fl_wet is not None:
            fl_wet_sum += fl_wet
    del chained

    # -- 4. the other voices, one at a time --------------------------------------------------
    doubles = [v for v in others if v.role == "double"]
    lead_original = sum((v.audio for v in leads), np.zeros(shape)) if leads and doubles else None
    copies = {v.key: stereo.copy_correlation(v.audio, lead_original, fs)
              for v in doubles if lead_original is not None}
    del lead_original
    placements = {p.key: p for p in stereo.plan_placement(
        [(v.key, v.label, v.role, v.audio) for v in others], copies, fs, k)}
    for v in others:
        say(f"Voix : {v.label}")
        processed, fl_wet, level, res = _chain(v, fs, k, fl_space.get(v.key, "none"), tempo_bpm)
        results[v.key] = res
        if v.role in RELATIVE_TO_LEAD and reference is not None and math.isfinite(level.lufs):
            current = res.loudness_after - results[reference.key].loudness_after
            change = _level_change(current, RELATIVE_TO_LEAD[v.role], k)
            if change > 0 and copies.get(v.key, 0.0) > stereo.COPY_CORRELATION:
                res.treatments.append(Treatment(
                    "gain", "Niveau gardé", "Copie de la voix principale : la monter créerait un filtrage "
                    "en peigne", {"gain_db": 0.0}))
                change = 0.0
            gain = 10 ** (set_level(v, change, f"{current:+.1f} dB par rapport à « {reference.label} »") / 20)
            processed = processed * gain
            fl_wet = fl_wet * gain if fl_wet is not None else None
        unplaced = processed  # what feeds Eden's sends: the voice before its pan
        placement = placements.get(v.key)
        if placement is not None:
            res.placement = placement.reason
            if placement.position:
                processed = stereo.place(processed, fs, placement)
        if env is not None and math.isfinite(level.lufs):
            processed = dsp.dip_band_when(processed, fs, env, size, SECONDARY_DIP_DB * k, 1000.0, 4000.0)
            res.treatments.append(Treatment(
                "dip", f"−{SECONDARY_DIP_DB * k:.1f} dB entre 1 et 4 kHz pendant la voix principale",
                "Les paroles de la voix principale passent devant"))
        add_space(v, unplaced, placement.position if placement and not placement.alternate else 0.0)
        voices_sum += processed
        if fl_wet is not None:
            fl_wet_sum += fl_wet

    # -- 5. reverb of the whole mix, level ------------------------------------------------------
    reverb_lu = -math.inf
    if returns_sum.any() or fl_wet_sum.any():
        dry = beat + voices_sum - fl_wet_sum
        scale, reverb_lu = returns_scale(fl_wet_sum, returns_sum, dry, fs, MAX_REVERB_LU)
        if scale < 1.0 and returns_sum.any():
            returns_sum *= scale
            note = (f"Effets d'Eden baissés de {-20 * math.log10(scale):.1f} dB" if scale > 0
                    else "Effets d'Eden retirés")
            for v in parts.voices:
                if results[v.key].space:
                    results[v.key].space.append(
                        f"{note} : la reverb de tout le morceau (tes effets FL compris) restait au-dessus de "
                        f"{MAX_REVERB_LU:.0f} LU")
        del dry
    final = beat + voices_sum + returns_sum
    staging = 0.0
    mix_lufs = integrated_loudness(final, fs)
    if math.isfinite(mix_lufs) and math.isfinite(premaster_lufs) and abs(premaster_lufs - mix_lufs) >= 0.01:
        staging = premaster_lufs - mix_lufs
        final = _gain(final, staging)
    ordered = [results[v.key] for v in parts.voices] + [results[g.key] for g in parts.groups]
    return MixOutcome(final, fs, k, ordered, song, staging, premaster_lufs, integrated_loudness(final, fs),
                      reverb_lu, warnings)
