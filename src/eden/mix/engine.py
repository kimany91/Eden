"""Eden's mix: what a rap mix engineer does, decided from measurements.

Everything is done on FL Studio's own renders (parts, see ``parts.py``):

1. the song: key (harmonic parts, the 808 settling relative keys, the
   beat's own tuning), tempo (from the project), the 808's notes against
   the key, kick / 808 collisions (all the drum groups against all the bass
   groups: FL often gives each drum its own insert), stereo of the low end;
2. the lead voices' chains (``vocal.py``), on FL's dry render when the voice
   carries FL reverbs or delays, which are then put back untouched;
3. the beat: room for the words (the bands where a dip makes the most of
   the lead's words audible are dipped while it sings, in the whole instru
   they were measured on: groups and rest of the mix, or the groups alone
   when voices were left in the rest of the mix),
   kick / 808 duck when they collide and nothing ducks already, harmonics
   for small speakers when the 808 is a bare sine. This comes before the
   balance, so the balance is measured on the beat as it will be heard;
4. the leads: level against the beat while they sing (leads that sing
   together are set as one; a warning when the change cannot bring them into
   the window), riding phrase by phrase (``riding.py``), space when they
   have none (``space.py``);
5. the other voices one by one: chain, level against the lead (copies of
   the lead are never raised: comb filtering; a warning when the change
   cannot bring them into their window), placement (``stereo.py``), a dip
   in 1–4 kHz of the voice alone (not its FL effects) while the lead sings,
   space when they have none;
6. the reverb of the whole mix (the user's FL effects and Eden's) is kept
   under a ceiling — when a voice's FL reverb could not be rendered apart,
   it cannot be measured, and Eden adds no space at all; the mix goes back
   to the level it came in at.

Voices are processed one at a time and added up as they are done, so
memory does not grow with the number of voices. At intensity 0 nothing is
changed: the result is the original pre-master mix, bit for bit. Every
change is recorded with its reason.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import combinations

import numpy as np

from eden.mix import dsp, lowend, stereo
from eden.mix.analysis import BandMasking, Level, balance_against, band_masking, level_of, measure_vocal
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
MAX_LEVEL_CHANGE_DB = 4.0  # static level change of the other voices against the lead
# static level change of a lead (or of leads that sing together) against the beat: a raw vocal over an
# already mastered beat often sits 10 dB under it (choix d'Eden)
MAX_LEAD_CHANGE_DB = 10.0
MAX_CARVE_DB = 3.0  # dip of the beat in one band while the lead sings
# bands left out of the carve (choix d'Eden): the beat covers the voice there by more than this, so a 1–3 dB
# dip uncovers nothing; the voice is this far under its strongest band there, so the band carries little of it
CARVE_MAX_MASKING_DB = 12.0
CARVE_VOICE_RANGE_DB = 20.0
CARVE_SHARE = 0.25  # the dip is reported on the groups / the rest of the mix that carry this share of what it removes
SECONDARY_DIP_DB = 2.0  # doubles / backs / ad-libs in 1–4 kHz while the lead sings
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
    # relative reverb loudness of the whole mix (De Man et al. 2017); NaN when an FL reverb inside a voice
    # could not be rendered apart, so cannot be measured
    reverb_lu: float
    warnings: list[str] = field(default_factory=list)


def _level_change(current: float, target: tuple[float, float, float], k: float, cap: float) -> float:
    """Static level change towards ``target`` (goal, lowest and highest accepted): none inside the
    window or without a measure, at most ``cap`` dB, scaled by the intensity ``k``."""
    goal, low, high = target
    if low <= current <= high or not math.isfinite(current):
        return 0.0
    return max(-cap, min(cap, goal - current)) * k


def _audibility(snr_db: float) -> float:
    """ANSI S3.5-1997 band audibility: 0 with the speech 15 dB under the noise, 1 from 15 dB over it."""
    return min(1.0, max(0.0, (snr_db + 15.0) / 30.0))


def _carve_bands(bands: list[BandMasking], k: float) -> list[tuple[BandMasking, float]]:
    """Up to 3 (band, depth) to dip in the beat while the lead sings.

    A band where the beat is 3 dB or more under the voice needs no dip; one it
    covers by more than ``CARVE_MAX_MASKING_DB`` cannot be uncovered by a dip
    of 1 to 3 dB; one where the voice is more than ``CARVE_VOICE_RANGE_DB``
    under its strongest band carries little of it. Each other band would dip
    from 1 dB (beat 3 dB under the voice) to ``MAX_CARVE_DB`` (beat 3 dB over
    it and more), scaled by ``k``; the ones whose dip makes the most of the
    words audible are kept: the band's importance times the audibility the
    dip gains (ANSI S3.5).
    """
    candidates = []
    for b in bands:
        if -3.0 < b.masking_db <= CARVE_MAX_MASKING_DB and b.voice_db >= -CARVE_VOICE_RANGE_DB:
            depth = min(MAX_CARVE_DB, 1.0 + (b.masking_db + 3.0) / 3.0) * k
            gained = b.weight * (_audibility(-b.masking_db + depth) - _audibility(-b.masking_db))
            candidates.append((gained, b, depth))
    candidates.sort(key=lambda c: c[0], reverse=True)
    return [(b, depth) for _, b, depth in candidates[:3]]


def _gain(x: np.ndarray, db: float) -> np.ndarray:
    return x * 10 ** (db / 20)


# groups that carry the chords: the full beat's kick and 808 stay under the 200 Hz the chords are read from
HARMONIC_ROLES = {"beat", "music", "fx", "unknown"}
HARMONY_FMIN_HZ = 200.0


def _sum_of(groups: list[Part], role: str) -> np.ndarray | None:
    """All the groups of one role added up (FL often gives each drum, or each 808 layer, its own insert)."""
    audio = [g.audio for g in groups if g.role == role]
    if len(audio) < 2:  # none, or the group itself: no copy
        return audio[0] if audio else None
    return sum(audio[1:], audio[0].astype(np.float64))


def analyse_song(parts: Parts, tempo_bpm: float | None) -> tuple[SongAnalysis, lowend.LowEndReport]:
    """Key from the harmonic parts (drums and 808 left out: their noise and partials blur the
    chroma), tonic settled by the 808, tuning of the beat, low end (all the bass groups together
    against all the drum groups together)."""
    fs = parts.sample_rate
    context = parts.residual.audio + sum((g.audio for g in parts.groups), np.zeros_like(parts.residual.audio))
    bass, drums = _sum_of(parts.groups, "bass"), _sum_of(parts.groups, "drums")
    harmonic = [g for g in parts.groups if g.role in HARMONIC_ROLES]
    harmony = (parts.residual.audio + sum((g.audio for g in harmonic), np.zeros_like(parts.residual.audio))
               if harmonic else context)
    cents = tuning(harmony, fs)
    bass_chroma = bass_pitch_classes(bass if bass is not None else context, fs, cents)
    # chords read above 200 Hz: below, kick, 808 and bass lines blur the chroma (Faraldo et al.);
    # the bass notes are given apart, to settle the tonic
    key = detect_key(harmony, fs, bass_chroma, fmin=HARMONY_FMIN_HZ, tuning_cents=cents)
    low = lowend.analyse(bass, drums, context, fs, key.scale if key else None, cents)
    song = SongAnalysis(key.display if key else None, key.confidence if key else None, cents, tempo_bpm,
                        felt_quarter(tempo_bpm) * 1000 if tempo_bpm else 500.0, low.root_name,
                        low.out_of_scale, low.detune_cents, low.kick_overlap, low.low_correlation,
                        low.harmonics_db)
    return song, low


def _chain(v: Part, fs: float, k: float, status: str, tempo_bpm: float | None
           ) -> tuple[np.ndarray, np.ndarray | None, Level, PartResult]:
    """One voice through its chain: (processed voice, its FL reverbs/delays part, level, result).
    Only the steps that changed something are reported; before and after are both the voice with
    its FL effects, as heard."""
    source = v.dry if v.dry is not None else v.audio
    m = measure_vocal(source, fs)
    treatments = plan_voice(m, v.role, k, status == "untracked")
    hold = tail_hold(m, source, fs, tempo_bpm) if status == "untracked" else None
    processed = apply(source, fs, treatments, hold=hold) if treatments else source
    treatments = [t for t in treatments if t.applied]
    fl_wet = None
    before = m.loudness_lufs
    if v.dry is not None:
        fl_wet = v.space
        processed = processed + fl_wet  # the user's FL reverbs and delays, untouched
        before = integrated_loudness(v.audio, fs)
    level = level_of(processed, fs) if treatments or fl_wet is not None else Level(m.loudness_lufs, m.active_blocks)
    return processed, fl_wet, level, PartResult(v.key, v.label, v.role, treatments, before, level.lufs, status)


def _sing_together(leads: list[Part], levels: dict[str, Level]) -> list[list[Part]]:
    """The leads, grouped with the ones they sing with (``stereo.together`` ≥ ``stereo.TOGETHER``,
    step by step: a hook take that sings with the verse lead joins it too)."""
    parent = list(range(len(leads)))

    def root(i: int) -> int:
        while parent[i] != i:
            i = parent[i]
        return i

    for i, j in combinations(range(len(leads)), 2):
        if stereo.together(levels[leads[i].key].active_blocks, levels[leads[j].key].active_blocks) >= stereo.TOGETHER:
            parent[root(j)] = root(i)
    clusters: dict[int, list[Part]] = {}
    for i, v in enumerate(leads):
        clusters.setdefault(root(i), []).append(v)
    return list(clusters.values())


def _copies(together: list[Part], fs: float) -> dict[str, tuple[str, float]]:
    """For each voice of ``together`` (in project order) that is a copy of another one, (label,
    correlation) of the one it copies most. When two copy each other (a duplicated track), the
    first one in project order counts as the original: only the later one is a copy."""
    corr = {(v.key, o.key): stereo.copy_correlation(v.audio, o.audio, fs)
            for v in together for o in together if o is not v}
    out = {}
    for i, v in enumerate(together):
        originals = [(o.label, corr[v.key, o.key]) for j, o in enumerate(together)
                     if j != i and corr[v.key, o.key] > stereo.COPY_CORRELATION
                     and (j < i or corr[o.key, v.key] <= stereo.COPY_CORRELATION)]
        if originals:
            out[v.key] = max(originals, key=lambda c: c[1])
    return out


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
    for g in parts.groups:
        if g.role != "bass":
            groups += g.audio
    basses = [g for g in parts.groups if g.role == "bass"]
    hits = None
    if low.kick_overlap > 0.5 and low.existing_duck_db < 2.0:  # measured only with drums and bass groups
        _, _, hits = lowend.kick_808_interaction(_sum_of(parts.groups, "bass"), _sum_of(parts.groups, "drums"), fs)
    if basses:
        say("Basses et 808")
    for g in basses:  # every bass group ducks on the same kicks: the ones measured against all of them
        audio = g.audio
        res = results[g.key]
        if hits is not None:
            audio = lowend.duck_low_band(audio, fs, hits, lowend.MAX_DUCK_DB * k)
            res.treatments.append(Treatment(
                "duck", f"808 baissé de {lowend.MAX_DUCK_DB * k:.1f} dB sous {lowend.CROSSOVER_HZ:.0f} Hz à chaque "
                f"kick ({hits.size} kicks)",
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
    residual = parts.residual.audio
    env = size = None
    if lead_mix is not None:
        level, _ = dsp.band_levels_db(lead_mix, fs)
        env, size = dsp.activity_envelope(lead_mix, fs, float(np.percentile(level, 95)) - 35.0,
                                          attack_ms=15.0, release_ms=200.0)
        # the instru is carved where it was measured: the groups and the rest of the mix (an instru that shares
        # a bus with the voices lands there), or the groups alone when voices were left in the rest of the mix
        # (they would be measured, and dipped, as instru); the dips are linear, carving each is carving their sum
        with_rest = not parts.voices_in_residual
        bands = band_masking(lead_mix, residual + groups if with_rest else groups, fs,
                             level_of(lead_mix, fs).active_blocks)
        chosen = _carve_bands(bands, k)
        if chosen:
            carved_groups, carved_residual = groups, residual
            for b, depth in chosen:
                carved_groups = dsp.dip_band_when(carved_groups, fs, env, size, depth, b.low_hz, b.high_hz)
                if with_rest:
                    carved_residual = dsp.dip_band_when(carved_residual, fs, env, size, depth, b.low_hz, b.high_hz)
            removed_groups = float(np.sum((groups - carved_groups) ** 2))
            removed_residual = float(np.sum((residual - carved_residual) ** 2))
            removed = removed_groups + removed_residual
            groups, residual = carved_groups, carved_residual
            del carved_groups, carved_residual
            carve = Treatment(
                "carve", "Place pour la voix : " + ", ".join(
                    f"{b.low_hz:.0f}–{b.high_hz:.0f} Hz −{d:.1f} dB" for b, d in chosen),
                "Bandes où un creux rend le plus de paroles audibles (importance de la bande pour les paroles × "
                "audibilité gagnée, ANSI S3.5), creusées seulement pendant le chant ; instru − voix dans ces "
                "bandes : " + ", ".join(f"{b.masking_db:+.1f} dB" for b, _ in chosen)
                + ". Choisies parmi les tiers d'octave de 250 Hz à 8 kHz où l'instru est à moins de 3 dB sous la "
                f"voix ou au-dessus, sans celles qu'elle couvre de plus de {CARVE_MAX_MASKING_DB:.0f} dB (un creux "
                f"de {MAX_CARVE_DB:.0f} dB n'y découvre rien) ni celles où la voix est à plus de "
                f"{CARVE_VOICE_RANGE_DB:.0f} dB sous sa bande la plus forte"
                + ("" if with_rest else " ; des voix sont restées dans le reste du mix : seuls les groupes sont "
                   "mesurés et creusés"))
            if removed > 0 and removed_groups / removed >= CARVE_SHARE:
                for g in parts.groups:
                    results[g.key].treatments.insert(0, carve)
                    results[g.key].loudness_after = math.nan  # carved inside the whole instru
            if removed > 0 and removed_residual / removed >= CARVE_SHARE:
                rest = parts.residual
                results[rest.key] = PartResult(rest.key, rest.label, rest.role, [carve],
                                               integrated_loudness(rest.audio, fs), math.nan)
        del lead_mix
    beat = residual + groups
    del groups, residual

    shape = parts.premaster.shape
    voices_sum, returns_sum, fl_wet_sum = np.zeros(shape), np.zeros(shape), np.zeros(shape)
    # an FL reverb left inside a voice cannot be measured: the reverb of the whole mix cannot be kept
    # under its ceiling, so Eden adds none of its own
    unmeasured = [f"« {v.label} »" for v in parts.voices if fl_space.get(v.key) == "untracked"]

    def add_space(v: Part, audio: np.ndarray, position: float = 0.0) -> None:
        nonlocal returns_sum
        if fl_space.get(v.key, "none") != "none" or not math.isfinite(results[v.key].loudness_after):
            return
        if unmeasured:
            results[v.key].space = [
                f"Pas d'espace ajouté : la reverb / le delay FL de {', '.join(unmeasured)} n'a pas pu être rendu à "
                f"part, Eden ne peut donc pas mesurer la reverb de tout le morceau ni la tenir sous "
                f"{MAX_REVERB_LU:.0f} LU"]
            return
        say(f"Espace : {v.label}")
        plan = design_space(tempo_bpm, v.role, k)
        wet, report = render_space(audio, fs, plan, k)
        returns_sum += stereo.balance(wet, position) if position else wet
        results[v.key].space = report + plan.notes

    def set_level(v: Part, change: float, what: str) -> None:
        if abs(change) < 0.1:
            return
        results[v.key].treatments.append(Treatment("gain", f"Niveau {change:+.1f} dB", f"Équilibre : {what}",
                                                   {"gain_db": change}))
        results[v.key].loudness_after += change
        results[v.key].level_change_db = change

    def still_off(who: str, plural: bool, against: str, balance: float, window: tuple[float, float, float],
                  fixes: tuple[str, str]) -> None:
        """Warn when a balance, Eden's level change made, is still outside its window; ``fixes``: what to
        do in FL Studio when it is too low, too high."""
        goal, low, high = window
        if math.isfinite(balance) and not low <= balance <= high:
            warnings.append(("À cette intensité, " if k < 1 else "")
                            + f"{who} reste{'nt' if plural else ''} à {balance:+.1f} dB {against}, niveau d'Eden "
                            f"compris (visé {goal:+.0f} dB, accepté de {low:+.0f} à {high:+.0f} dB) : "
                            + fixes[balance > high])

    # -- 3. the leads: balance against the beat, riding, space -----------------------------
    say("Équilibre et suivi de la voix principale")
    target = (f"visé {LEAD_BALANCE[0]:+.0f} dB, accepté de {LEAD_BALANCE[1]:+.0f} à {LEAD_BALANCE[2]:+.0f} dB "
              "(mesure BS.1770, où une voix lit environ 2 LU plus bas qu'à l'oreille)")
    for together in _sing_together(sung, {v.key: chained[v.key][2] for v in sung}):
        if len(together) == 1:
            v = together[0]
            current = balance_against(chained[v.key][2], beat, fs)
            set_level(v, _level_change(current, LEAD_BALANCE, k, MAX_LEAD_CHANGE_DB),
                      f"voix {current:+.1f} dB par rapport à l'instru pendant qu'elle chante ; {target}")
            # a static gain moves the balance by exactly that many dB
            still_off(f"« {v.label} »", False, "de l'instru pendant qu'elle chante",
                      current + results[v.key].level_change_db, LEAD_BALANCE,
                      ("monte la voix ou baisse l'instru dans FL Studio",
                       "baisse la voix ou monte l'instru dans FL Studio"))
            continue
        # takes sung at the same moments add up: they are set as one, their balance kept
        stack = sum((chained[v.key][0] for v in together), np.zeros(shape))
        current = balance_against(level_of(stack, fs), beat, fs)
        del stack
        change = _level_change(current, LEAD_BALANCE, k, MAX_LEAD_CHANGE_DB)
        copied = _copies(together, fs) if change > 0 else {}
        kept = [f"« {v.label} »" for v in together if v.key in copied]
        s = "s" if len(kept) > 1 else ""
        names = " + ".join(f"« {v.label} »" for v in together)
        what = (names + f", qui chantent ensemble : {current:+.1f} dB "
                "par rapport à l'instru pendant qu'elles chantent, réglées d'un même gain"
                + (f" sauf {', '.join(kept)} (copie{s}, jamais montée{s})" if kept else "") + f" ; {target}")
        for v in together:
            if v.key in copied:
                label, corr = copied[v.key]
                results[v.key].treatments.append(Treatment(
                    "gain", "Niveau gardé", f"Copie de « {label} » (corrélation {corr:.2f}) : une copie "
                    "n'est jamais montée (filtrage en peigne)", {"gain_db": 0.0}))
            else:
                set_level(v, change, what)
        gains = {results[v.key].level_change_db for v in together}
        if len(gains) > 1:  # copies kept at their level: the stack is measured again
            stack = sum((chained[v.key][0] * 10 ** (results[v.key].level_change_db / 20) for v in together),
                        np.zeros(shape))
            after = balance_against(level_of(stack, fs), beat, fs)
            del stack
        else:
            after = current + gains.pop()
        still_off(f"{names}, qui chantent ensemble,", True, "de l'instru pendant qu'elles chantent", after,
                  LEAD_BALANCE, ("monte ces voix ou baisse l'instru dans FL Studio",
                                 "baisse ces voix ou monte l'instru dans FL Studio"))
    reference = None
    for v in leads:
        processed, fl_wet, level, _ = chained.pop(v.key)
        if math.isfinite(level.lufs):
            gain = 10 ** (results[v.key].level_change_db / 20)
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
                    f"tout le morceau) ; écart toléré ±{TOLERANCE_DB:.1f} dB ; baissée seulement de ce dont la voix "
                    "elle-même dépasse sa phrase médiane, jamais parce que l'instru se retire"
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
    # placement is decided on the voice without its FL effects: a stereo FL reverb is not a placement
    placements = {p.key: p for p in stereo.plan_placement(
        [(v.key, v.label, v.role, v.dry if v.dry is not None else v.audio) for v in others], copies, fs, k)}
    for v in others:
        say(f"Voix : {v.label}")
        processed, fl_wet, level, res = _chain(v, fs, k, fl_space.get(v.key, "none"), tempo_bpm)
        results[v.key] = res
        if v.role in RELATIVE_TO_LEAD and reference is not None and math.isfinite(level.lufs):
            current = res.loudness_after - results[reference.key].loudness_after
            change = _level_change(current, RELATIVE_TO_LEAD[v.role], k, MAX_LEVEL_CHANGE_DB)
            if change > 0 and copies.get(v.key, 0.0) > stereo.COPY_CORRELATION:
                res.treatments.append(Treatment(
                    "gain", "Niveau gardé", "Copie de la voix principale : la monter créerait un filtrage "
                    "en peigne", {"gain_db": 0.0}))
            else:
                set_level(v, change, f"{current:+.1f} dB par rapport à « {reference.label} »")
                still_off(f"« {v.label} »", False, f"de « {reference.label} »", current + res.level_change_db,
                          RELATIVE_TO_LEAD[v.role],
                          ("monte cette voix dans FL Studio", "baisse cette voix dans FL Studio"))
            gain = 10 ** (res.level_change_db / 20)
            processed = processed * gain
            fl_wet = fl_wet * gain if fl_wet is not None else None
        unplaced = processed  # what feeds Eden's sends: the voice before its dip and pan
        if env is not None and math.isfinite(level.lufs):
            # the voice alone: the user's FL reverbs and delays come back as they are. The dip comes before
            # the pan, which it commutes with (an ad-lib's phrases are then found on the dipped voice)
            alone = processed - fl_wet if fl_wet is not None else processed
            processed = dsp.dip_band_when(alone, fs, env, size, SECONDARY_DIP_DB * k, 1000.0, 4000.0)
            if fl_wet is not None:
                processed = processed + fl_wet
            res.treatments.append(Treatment(
                "dip", f"−{SECONDARY_DIP_DB * k:.1f} dB entre 1 et 4 kHz pendant la voix principale",
                "Les paroles de la voix principale passent devant" + (" ; tes reverbs et delays FL restent tels "
                                                                      "quels" if fl_wet is not None else "")))
        placement = placements.get(v.key)
        if placement is not None:
            res.placement = placement.reason
            if placement.position:
                processed = stereo.place(processed, fs, placement, fl_wet)
        add_space(v, unplaced, placement.position if placement and not placement.alternate else 0.0)
        voices_sum += processed
        if fl_wet is not None:
            fl_wet_sum += fl_wet

    # -- 5. reverb of the whole mix, level ------------------------------------------------------
    reverb_lu = -math.inf
    if unmeasured:
        reverb_lu = math.nan
    elif returns_sum.any() or fl_wet_sum.any():
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
    ordered = [results[p.key] for p in [*parts.voices, *parts.groups, parts.residual] if p.key in results]
    return MixOutcome(final, fs, k, ordered, song, staging, premaster_lufs, integrated_loudness(final, fs),
                      reverb_lu, warnings)
