"""Mix engine, fourth review round: a lead whose FL reverb or delay was rendered apart is ridden like
the same lead without it, drums without a kick do not duck the 808, the kick hits are read once,
copies among the leads are read once per voice and only between voices that sing together, the
carve is chosen with the lead at the level Eden plans for it, the reverb ceiling says when the
user's FL effects alone go over it, and the texts and docs say what the code does."""

import functools
import math
from dataclasses import fields
from pathlib import Path

import numpy as np
import pytest
from scipy.signal import butter, oaconvolve, sosfilt

from eden.mix import dsp, engine, lowend, riding, space, stereo
from eden.mix.analysis import balance_against, band_masking, level_of
from eden.mix.engine import CARVE_MAX_MASKING_DB, LEAD_BALANCE, MAX_CARVE_DB, MAX_REVERB_LU, MixOutcome, mix
from eden.mix.parts import Part, Parts
from synth_voice import FS, beat, voice
from test_engine_mix import KICK_EVERY_S, _808, _against, _fl_reverb, _hats, _keys, _kicks, _parts, _snare, _stereo

DOC = (Path(__file__).resolve().parent.parent / "docs" / "mixage.md").read_text(encoding="utf-8")
SECONDS = 24.0
TEMPO = 95.0


def _french(value: float) -> str:
    return f"{value:g}".replace(".", ",")


# -- riding a lead whose FL effects were rendered apart ----------------------------------------------

def _phrased(seconds: float = SECONDS, rest_s: float = 0.6, phrase_s: float = 2.4, spread_db: float = 6.0,
             seed: int = 11) -> np.ndarray:
    """A lead in phrases of ``phrase_s`` s, each at its own level (±``spread_db``), with rests of ``rest_s`` s."""
    rng = np.random.default_rng(seed + 100)
    src = voice(2 * seconds, seed=seed, phrase_spread_db=0)
    src = src[np.arange(src.shape[0]) % (5 * FS) < 4 * FS]  # the synthetic voice's own pauses taken out
    out, pos = [], 0
    while pos + int(phrase_s * FS) < src.shape[0]:
        out.append(src[pos:pos + int(phrase_s * FS)] * 10 ** (rng.uniform(-spread_db, spread_db) / 20))
        out.append(np.zeros((int(rest_s * FS), 2)))
        pos += int(phrase_s * FS)
    return np.concatenate(out)[:int(seconds * FS)]


def _echo(x: np.ndarray, level_db: float = -15.0, repeats: int = 2) -> np.ndarray:
    """An FL echo on the quarter note, each repeat ``level_db`` under the one before."""
    step = int(60 / TEMPO * FS)
    out = np.zeros_like(x)
    for i in range(1, repeats + 1):
        out[i * step:] += 10 ** (i * level_db / 20) * x[:-i * step]
    return out


def _reverb(x: np.ndarray, rt60_s: float = 1.5, level_db: float = -18.0) -> np.ndarray:
    """An FL reverb whose tail falls 60 dB in ``rt60_s``, 20 ms pre-delay, ``level_db`` under the voice."""
    rng = np.random.default_rng(5)
    n = int(rt60_s * FS)
    ir = rng.normal(0, 1, (n, 2)) * np.exp(-6.9 * np.arange(n) / n)[:, None]
    ir[:int(0.02 * FS)] = 0
    wet = np.stack([oaconvolve(x[:, c], ir[:, c])[:x.shape[0]] for c in range(2)], axis=1)
    return wet * math.sqrt(np.sum(x ** 2) / np.sum(wet ** 2)) * 10 ** (level_db / 20)


@functools.cache
def _ridden_without_fl_effects():
    out = mix(_parts([("ch0", "Lead", "lead_vocal", _phrased(), None)], [("g1", "Instru", "beat", beat(SECONDS))]),
              1.0, TEMPO, {"ch0": "none"})
    return out.parts[0]


@pytest.mark.parametrize("effect, one_phrase", [(_echo, True), (_reverb, False)], ids=["echo 1/4", "reverb 1.5 s"])
def test_a_lead_whose_fl_effects_were_rendered_apart_is_ridden_like_the_same_lead_without_them(
        effect, one_phrase, monkeypatch):
    lead, instru = _phrased(), beat(SECONDS)
    wet = effect(lead)
    # read on the voice with its FL effects, the tails fill the rests and join the phrases; the echo makes the
    # whole song one phrase, and nothing is ridden (docs/mixage.md § 3)
    alone = len(riding.phrase_levels(lead, instru, FS, TEMPO)[0])
    with_effects = len(riding.phrase_levels(lead + wet, instru, FS, TEMPO)[0])
    assert with_effects < alone
    if one_phrase:
        assert with_effects == 1 and riding.ride(lead + wet, instru, FS, TEMPO, 1.0).moved == 0
    reference = _ridden_without_fl_effects()
    ridden = []
    apply_ride = engine.apply_ride
    monkeypatch.setattr(engine, "apply_ride", lambda x, r: ridden.append((x.copy(), r)) or apply_ride(x, r))
    out = mix(_parts([("ch0", "Lead", "lead_vocal", lead + wet, lead)], [("g1", "Instru", "beat", instru)]),
              1.0, TEMPO, {"ch0": "tracked"})
    res = out.parts[0]
    assert reference.ride["phrases"] == alone and reference.ride["moved"] == 3
    assert res.ride["phrases"] == reference.ride["phrases"] and res.ride["moved"] == reference.ride["moved"]
    assert res.ride["max_change_db"] == pytest.approx(reference.ride["max_change_db"], abs=0.01)
    ride = next(t for t in res.treatments if t.kind == "ride")
    assert ride.reason.endswith("; phrases lues sur la voix sans tes reverbs et delays FL (leurs queues "
                                "rempliraient les silences), qui reçoivent le même gain")
    # the voice (kept in 32-bit float until the leads are balanced) and its FL effects get the same ride
    (voice_ridden, ride_voice), (effects_ridden, ride_effects) = ridden
    assert ride_voice is ride_effects and voice_ridden.dtype == np.float32
    assert np.allclose(effects_ridden, wet * 10 ** (res.level_change_db / 20), atol=1e-6)


# -- drums without a kick ---------------------------------------------------------------------------

S = 12.0
RNG_SEED = 1


def _kick_layers(click: float = 0.0, f0: float = 50.0, tau_s: float = 0.08) -> tuple[np.ndarray, np.ndarray]:
    """One kick: a pitched-down sine thump and a click layer (noise above 2 kHz, 4 ms decay) weighted ``click``."""
    rng = np.random.default_rng(RNG_SEED)
    t = np.arange(int(0.3 * FS)) / FS
    thump = 0.6 * np.sin(2 * np.pi * np.cumsum(f0 + 100 * np.exp(-t / 0.02)) / FS) * np.exp(-t / tau_s)
    noise = sosfilt(butter(2, 2000, btype="highpass", fs=FS, output="sos"), rng.normal(0, 1, t.size))
    return thump, click * noise * np.exp(-t / 0.004)


def _kick(click: float = 0.0, f0: float = 50.0, tau_s: float = 0.08) -> tuple[np.ndarray, int]:
    """A kick (``_kick_layers``) every quarter note at 140 BPM, and how many there are."""
    hit = sum(_kick_layers(click, f0, tau_s))
    out = np.zeros(int(S * FS))
    starts = np.arange(0.2, S - 0.3, KICK_EVERY_S)
    for s in starts:
        out[int(s * FS):int(s * FS) + hit.size] += hit
    return _stereo(out), starts.size


def _crash() -> np.ndarray:
    """A crash on every bar, on the kick."""
    rng = np.random.default_rng(RNG_SEED)
    t = np.arange(int(1.5 * FS)) / FS
    hit = 0.4 * sosfilt(butter(2, 3000, btype="highpass", fs=FS, output="sos"), rng.normal(0, 1, t.size)) * np.exp(-t / 0.5)
    out = np.zeros(int(S * FS))
    for s in np.arange(0.2, S - 1.6, 4 * KICK_EVERY_S):
        out[int(s * FS):int(s * FS) + hit.size] += hit
    return _stereo(out)


def _drum(body_hz: float) -> np.ndarray:
    """A snare (or a tom) on beats 2 and 4: a body at ``body_hz`` and noise above 1.5 kHz."""
    rng = np.random.default_rng(RNG_SEED)
    t = np.arange(int(0.25 * FS)) / FS
    body = np.sin(2 * np.pi * (body_hz + 60 * np.exp(-t / 0.01)) * t) * np.exp(-t / 0.06)
    noise = sosfilt(butter(2, 1500, btype="highpass", fs=FS, output="sos"), rng.normal(0, 0.5, t.size))
    hit = 0.4 * (body + noise * np.exp(-t / 0.08))
    out = np.zeros(int(S * FS))
    for s in np.arange(KICK_EVERY_S, S - 0.3, 2 * KICK_EVERY_S):
        out[int(s * FS):int(s * FS) + hit.size] += hit
    return _stereo(out)


def test_the_click_layer_of_the_clickiest_test_kick_carries_8_db_more_than_its_thump():
    thump, click = (layer[:int(0.03 * FS)] for layer in _kick_layers(click=4.0))  # its first 30 ms
    assert 10 * math.log10(np.sum(click ** 2) / np.sum(thump ** 2)) == pytest.approx(8.0, abs=0.1)


def _hits_of_any_kind(x: np.ndarray, monkeypatch) -> np.ndarray:
    with monkeypatch.context() as m:
        m.setattr(lowend, "KICK_LOW_SHARE", 0.0)
        return lowend._onsets(x, FS)


def _low_share(x: np.ndarray, hits: np.ndarray) -> np.ndarray:
    """The share of each hit's power over its first 30 ms that the band below 150 Hz carries."""
    low, full = lowend._low_power(x, FS, 150.0), dsp._frames(x, FS)[0]
    head = lowend.KICK_HEAD_MS
    return np.array([low[h:h + head].sum() / full[h:h + head].sum() for h in hits])


@pytest.mark.parametrize("drums, low, high, kicks", [
    (lambda: _hats(S), 0.0, 0.001, False),
    (lambda: _snare(S), 0.0, 0.04, False),
    (lambda: _drum(180.0), 0.0, 0.04, False),
    (lambda: _drum(200.0), 0.0, 0.04, False),
    (lambda: _kick()[0], 0.81, 0.83, True),
    (lambda: _kick(click=4.0)[0], 0.11, 0.12, True),
    (lambda: _kick(click=1.0, f0=60.0, tau_s=0.04)[0] + _crash(), 0.18, 0.46, True),
    (lambda: _drum(120.0), 0.43, 0.45, True),  # a tom whose body is under 150 Hz reads as a kick
], ids=["hats", "snare", "snare body 180 Hz", "snare body 200 Hz", "kick", "kick with a click 4x",
        "tight kick under a crash", "tom body 120 Hz"])
def test_a_hit_is_a_kick_when_its_low_band_carries_a_tenth_of_its_first_30_ms(drums, low, high, kicks, monkeypatch):
    x = drums()
    hits = _hits_of_any_kind(x, monkeypatch)  # what the threshold, which follows the drums' own low band, finds
    share = _low_share(x, hits)
    assert hits.size >= 14 and low <= share.min() and share.max() <= high  # the figures in docs/mixage.md § 1
    assert np.array_equal(lowend._onsets(x, FS), hits if kicks else np.zeros(0, dtype=int))


def _duck(out, key="g2"):
    return [t for t in next(p for p in out.parts if p.key == key).treatments if t.kind == "duck"]


@pytest.mark.parametrize("groups", [
    lambda: [("g1", "Beat", "beat", _keys(S) + _kicks(S)[0]), ("g2", "808", "bass", _808(S)),
             ("g3", "Hi Hat", "drums", _hats(S))],
    lambda: [("g1", "Beat", "beat", _keys(S) + _kicks(S)[0]), ("g2", "808", "bass", _808(S)),
             ("g3", "Snare", "drums", _snare(S))],
    lambda: [("g1", "Keys", "music", _keys(S)), ("g2", "808", "bass", _808(S)), ("g3", "Hi Hat", "drums", _hats(S)),
             ("g4", "Snare", "drums", _drum(180.0))],
], ids=["kick in the beat, hats apart", "kick in the beat, snare apart", "no kick, the 808 holds the low end"])
def test_a_drums_group_without_a_kick_does_not_duck_the_808(groups, monkeypatch):
    layout = groups()
    drums = sum(audio for _, _, role, audio in layout if role == "drums")
    assert _hits_of_any_kind(drums, monkeypatch).size >= 14  # what would have been read as kicks
    out = mix(_parts([], layout), 1.0, 140.0, {})
    assert out.song.kick_overlap == 0.0 and not _duck(out)


def test_the_kick_hits_are_read_once_and_the_808_ducks_on_them(monkeypatch):
    calls, ducked = [], []
    interaction, duck_low_band = lowend.kick_808_interaction, lowend.duck_low_band
    monkeypatch.setattr(lowend, "kick_808_interaction", lambda b, d, fs: calls.append(1) or interaction(b, d, fs))
    monkeypatch.setattr(lowend, "duck_low_band",
                        lambda x, fs, hits, depth: ducked.append(hits) or duck_low_band(x, fs, hits, depth))
    kicks, count = _kicks(S)
    parts = _parts([], [("g1", "Kick", "drums", kicks), ("g2", "808", "bass", _808(S)), ("g3", "Keys", "music", _keys(S))])
    out = mix(parts, 1.0, 140.0, {})
    assert len(calls) == 1 and _duck(out)
    [hits] = ducked
    assert abs(hits.size - count) <= 1
    report = lowend.analyse(parts.groups[1].audio, parts.groups[0].audio, parts.premaster, FS, None)
    assert np.array_equal(hits, report.kick_hits)
    assert "kick_hits" in {f.name for f in fields(lowend.LowEndReport)}
    assert "actions" not in {f.name for f in fields(lowend.LowEndReport)} and not hasattr(lowend, "SUB_BAND")


# -- copies among the leads ---------------------------------------------------------------------------

def _sung(x: np.ndarray, start_s: float, end_s: float) -> np.ndarray:
    out = np.zeros_like(x)
    out[int(start_s * FS):int(end_s * FS)] = x[int(start_s * FS):int(end_s * FS)]
    return out


def test_copies_among_leads_are_read_once_per_voice_and_only_between_voices_that_sing_together(monkeypatch):
    seconds = 20.0
    a = _sung(voice(seconds, seed=11), 0.0, 10.0)
    audio = {"a": a, "b": 0.7 * np.roll(a, int(0.01 * FS), axis=0),  # a copy of A, 10 ms late
             "c": voice(seconds, seed=13), "d": _sung(voice(seconds, seed=12), 10.0, 20.0)}
    takes = [Part(key, key.upper(), "vocal", x.astype(np.float32), [i]) for i, (key, x) in enumerate(audio.items())]
    levels = {v.key: level_of(v.audio, FS) for v in takes}
    together = {(v.key, o.key) for v in takes for o in takes if o is not v
                and stereo.together(levels[v.key].active_blocks, levels[o.key].active_blocks) >= stereo.TOGETHER}
    assert together == {(v, o) for v in "abc" for o in "abc" if v != o} | {("c", "d"), ("d", "c")}
    decimated, correlated = [], []
    resample_poly, lag_correlation = engine.resample_poly, engine._lag_correlation
    monkeypatch.setattr(engine, "resample_poly", lambda x, up, down: decimated.append(1) or resample_poly(x, up, down))
    monkeypatch.setattr(engine, "_lag_correlation", lambda f, d, lag: correlated.append(1) or lag_correlation(f, d, lag))
    copies = engine._copies(takes, levels, FS)
    assert len(decimated) == 4 and len(correlated) == len(together) == 8  # A and B are never compared with D
    # the same measure as stereo.copy_correlation: the later of two takes that copy each other is the copy
    assert copies == {"b": ("A", pytest.approx(stereo.copy_correlation(takes[1].audio, takes[0].audio, FS), abs=1e-6))}
    assert copies["b"][1] > 0.99


# -- the carve, chosen with the lead at its planned level ---------------------------------------------------

def test_the_same_lead_rendered_14_db_quieter_gets_the_same_carve(monkeypatch):
    instru = beat(SECONDS)
    loud = _against(voice(SECONDS, seed=1), instru, 7.0)  # brought down to the target
    quiet = loud * 10 ** (-14 / 20)  # brought up by 8 dB, under the 10 dB cap, to the same target
    measured = []
    masking = engine.band_masking
    monkeypatch.setattr(engine, "band_masking", lambda v, o, fs, m: measured.append((v, o, m)) or masking(v, o, fs, m))
    carves, changes = [], []
    for lead in (loud, quiet):
        out = mix(_parts([("ch0", "Lead", "lead_vocal", lead, None)], [("g1", "Instru", "beat", instru)]),
                  1.0, TEMPO, {"ch0": "none"})
        carves.append(next(t for t in out.parts[1].treatments if t.kind == "carve"))
        changes.append(out.parts[0].level_change_db)
    assert changes[1] - changes[0] == pytest.approx(14.0, abs=0.05) and changes[0] < -4.0 and changes[1] > 4.0
    bands = [sorted(carve.label.removeprefix("Place pour la voix : ").split(", ")) for carve in carves]
    assert bands[0] == bands[1] and len(bands[0]) == 3  # in the same order but for ties (equal depth and weight)
    # measured with the lead at the level Eden plans for it: the balance's target, on the beat before the carve
    for vocal, _, _ in measured:
        assert balance_against(level_of(vocal, FS), instru, FS) == pytest.approx(LEAD_BALANCE[0], abs=0.05)
    assert "instru − voix dans ces bandes, la voix au niveau prévu par Eden : " in carves[0].reason
    # measured as the chain gives them, before their level change, the two leads would have read other bands,
    # each its own
    chosen = [b.low_hz for b, _ in engine._carve_bands(masking(*measured[0][:2], FS, measured[0][2]), 1.0)]
    as_rendered = [[b.low_hz for b, _ in engine._carve_bands(band_masking(v * 10 ** (-change / 20), o, FS, m), 1.0)]
                   for (v, o, m), change in zip(measured, changes, strict=True)]
    assert as_rendered[0] != chosen and as_rendered[1] != chosen and as_rendered[0] != as_rendered[1]


def test_bands_the_beat_covers_by_more_than_12_db_are_left_out_as_a_choice():
    # beyond 12 dB, even the deepest dip leaves the voice more than 9 dB under the beat, as the reason says
    band = engine.BandMasking(1782.0, 2245.0, CARVE_MAX_MASKING_DB, 0.0883, 0.0)
    [(_, depth)] = engine._carve_bands([band], 1.0)
    assert depth == MAX_CARVE_DB and CARVE_MAX_MASKING_DB - depth == 9.0
    assert engine._carve_bands([engine.BandMasking(1782.0, 2245.0, CARVE_MAX_MASKING_DB + 0.01, 0.0883, 0.0)], 1.0) == []
    # by ANSI S3.5's audibility the dip would gain there as much as in the bands kept: it is a choice
    gained = engine._audibility(-(CARVE_MAX_MASKING_DB + 1) + MAX_CARVE_DB) - engine._audibility(-(CARVE_MAX_MASKING_DB + 1))
    assert gained == pytest.approx(MAX_CARVE_DB / 30)


# -- the reverb ceiling when the user's FL effects alone go over it -----------------------------------------

def _wet_lead(level_db: float, *others) -> Parts:
    dry = voice(16.0, seed=1, level=0.2)
    return _parts([("ch0", "Lead", "lead_vocal", dry + _fl_reverb(dry[:, 0], level_db), dry), *others],
                  [("g1", "Instru", "beat", beat(16.0, level=0.15))])


def test_when_the_fl_effects_alone_go_over_the_reverb_ceiling_the_mix_says_so():
    out = mix(_wet_lead(-4.0), 1.0, 140.0, {"ch0": "tracked"})
    assert out.reverb_lu > MAX_REVERB_LU + 3
    assert out.warnings == [f"La reverb de tout le morceau est à {out.reverb_lu:.1f} LU par rapport au mix sec, "
                            "au-dessus du plafond de -16 LU : les reverbs et delays FL de « Lead » suffisent à le "
                            "dépasser ; baisse-les dans FL Studio"]


def test_eden_sends_taken_out_by_the_ceiling_are_no_longer_listed(monkeypatch):
    scales = []
    returns_scale = engine.returns_scale
    monkeypatch.setattr(engine, "returns_scale",
                        lambda *a: scales.append(returns_scale(*a)) or scales[-1])
    double = ("ch1", "Double", "double", voice(16.0, seed=3, level=0.1), None)
    out = mix(_wet_lead(-4.0, double), 1.0, 140.0, {"ch0": "tracked", "ch1": "none"})
    [(scale, reverb_lu)] = scales
    assert scale == 0.0 and reverb_lu == out.reverb_lu > MAX_REVERB_LU
    res = {p.key: p for p in out.parts}
    assert res["ch1"].space == [f"Effets d'Eden retirés : avec tes seuls effets FL, la reverb de tout le morceau est "
                                f"déjà à {reverb_lu:.1f} LU par rapport au mix sec (plafond -16 LU)"]
    assert [w for w in out.warnings if w.startswith("La reverb")] == [
        f"La reverb de tout le morceau est à {reverb_lu:.1f} LU par rapport au mix sec, au-dessus du plafond de "
        "-16 LU : les reverbs et delays FL de « Lead » suffisent à le dépasser (Eden a retiré les siens) ; "
        "baisse-les dans FL Studio"]


def test_fl_effects_under_the_ceiling_bring_no_warning():
    out = mix(_wet_lead(-20.0), 1.0, 140.0, {"ch0": "tracked"})
    assert -math.inf < out.reverb_lu <= MAX_REVERB_LU and out.warnings == []


def test_the_mix_outcome_keeps_the_reverb_and_drops_the_loudness_nothing_read():
    names = {f.name for f in fields(MixOutcome)}
    assert "reverb_lu" in names and not {"loudness_original", "loudness_mix"} & names


# -- texts and docs -------------------------------------------------------------------------------

def test_the_space_report_gives_each_duck_as_it_is():
    plan = space.design_space(TEMPO, "lead_vocal", 1.0)
    _, report = space.render_space(voice(8.0, seed=1), FS, plan, 1.0)
    ducks = {send.name: send.duck_db for send in plan.sends}
    assert ducks == {"ambience": 0.0, "plate": 2.5, "delay": 10.0, "throw": 10.0}
    lines = dict(zip([send.name for send in plan.sends], report, strict=True))
    assert lines["plate"].endswith(", baissé de 2.5 dB pendant qu'elle chante")
    assert lines["throw"].endswith(", baissé de 10 dB pendant qu'elle chante")
    table = DOC.split("## 4. ")[1].split("## 5. ")[0]
    for name, row in (("plate", "| Plate |"), ("delay", "| Delay 1/8 |"), ("throw", "| Jet d'écho (lead) |")):
        line = next(line for line in table.splitlines() if line.startswith(row))
        assert f"de {_french(ducks[name])} dB pendant le chant" in line
    throw = next(line for line in table.splitlines() if line.startswith("| Jet d'écho (lead) |"))
    assert "remonte en un quart du temps de delay" in throw


def test_the_docs_state_the_engine_rules():
    kick_row = next(line for line in DOC.split("## 1. ")[1].split("## 2. ")[0].splitlines()
                    if line.startswith("| Kick / 808 |"))
    assert f"au moins {lowend.KICK_LOW_SHARE * 100:.0f} % de sa puissance sur ses {lowend.KICK_HEAD_MS} premières ms" \
        in kick_row
    unmask = " ".join(DOC.split("## 6. ")[1].split("## 7. ")[0].split())
    assert "n'y découvre rien" not in DOC and "(méthode de Hafezi & Reiss 2015, sourcé)" not in unmask
    assert (f"plus de {CARVE_MAX_MASKING_DB:.0f} dB (même creusée de {MAX_CARVE_DB:.0f} dB, la voix y resterait à plus "
            f"de {CARVE_MAX_MASKING_DB - MAX_CARVE_DB:.0f} dB sous l'instru") in unmask
    assert ("Le creux ne joue que quand la voix chante (comme l'« Unmask » des égaliseurs dynamiques, non vérifié ; "
            "choix d'Eden) ; baisser l'instru là où elle masque la voix est la méthode de Hafezi & Reiss 2015 "
            "(sourcé)") in unmask
    ceiling = " ".join(DOC.split("## 4. ")[1].split("## 5. ")[0].split())
    assert "Si tes effets dépassent déjà ce plafond à eux seuls, Eden retire les siens et te le signale" in ceiling
