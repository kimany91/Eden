"""Mix engine, second review round: a buried lead and the warnings when a voice stays off its window,
the bands carved for the words, the other voices' dip that leaves their FL effects alone, duplicated
lead tracks, and voices left in the rest of the mix."""

import math
import re

import numpy as np
import pytest

from eden.mix import dsp, engine
from eden.mix.analysis import SII_OCTAVE_WEIGHTS, BandMasking, band_masking
from eden.mix.engine import MAX_LEAD_CHANGE_DB, mix
from eden.mix.parts import Parts, split
from eden.project.inspector import inspect_project
from eden.project.sources import SearchRoots
from eden.render import plan
from eden.render.pipeline import render_project
from synth_voice import FS, beat, voice
from test_engine_mix import _808, _against, _fl_reverb, _hats, _keys, _kicks, _parts, _snare, _sung_only
from test_render import make_session, sim_renderer

SECONDS = 16.0


def _gain(result) -> tuple[float, str]:
    t = next(t for t in result.treatments if t.kind == "gain")
    return t.params["gain_db"], t.reason


def _before(reason: str) -> float:
    """The balance before Eden's change, as the gain's reason states it."""
    return float(re.search(r"([+-]\d+\.\d) dB par rapport à", reason).group(1))


def _stays_at(warning: str) -> float:
    return float(re.search(r"reste(?:nt)? à ([+-]\d+\.\d) dB", warning).group(1))


# -- a buried lead --------------------------------------------------------------------------------

def test_a_lead_far_under_the_beat_is_raised_by_more_than_4_db():
    instru = beat(SECONDS)
    lead = _against(voice(SECONDS, seed=11), instru, -8.0)
    out = mix(_parts([("ch0", "Lead", "lead_vocal", lead, None)], [("g1", "Instru", "beat", instru)]),
              1.0, 95.0, {"ch0": "none"})
    gain, reason = _gain(out.parts[0])
    assert 4.0 < gain < MAX_LEAD_CHANGE_DB
    assert _before(reason) + gain == pytest.approx(engine.LEAD_BALANCE[0], abs=0.06)  # on target
    assert out.warnings == []


def test_a_lead_still_buried_after_10_db_is_named_with_what_is_left():
    instru = beat(SECONDS)
    lead = _against(voice(SECONDS, seed=11), instru, -16.0)
    out = mix(_parts([("ch0", "Lead", "lead_vocal", lead, None)], [("g1", "Instru", "beat", instru)]),
              1.0, 95.0, {"ch0": "none"})
    gain, reason = _gain(out.parts[0])
    assert gain == MAX_LEAD_CHANGE_DB
    [warning] = out.warnings
    # a static gain moves the balance by exactly that many dB
    assert _stays_at(warning) == pytest.approx(_before(reason) + gain, abs=0.11)
    assert warning.startswith("« Lead » reste à -") and warning.endswith(
        "de l'instru pendant qu'elle chante, niveau d'Eden compris (visé +1 dB, accepté de -1 à +4 dB) : "
        "monte la voix ou baisse l'instru dans FL Studio")


def test_at_a_lower_intensity_the_warning_says_so():
    instru = beat(SECONDS)
    lead = _against(voice(SECONDS, seed=11), instru, -8.0)
    parts = _parts([("ch0", "Lead", "lead_vocal", lead, None)], [("g1", "Instru", "beat", instru)])
    out = mix(parts, 0.5, 95.0, {"ch0": "none"})
    gain, reason = _gain(out.parts[0])
    assert gain == pytest.approx((engine.LEAD_BALANCE[0] - _before(reason)) * 0.5, abs=0.06)  # k scales the move
    [warning] = out.warnings
    assert warning.startswith("À cette intensité, « Lead » reste à -")
    assert _stays_at(warning) == pytest.approx(_before(reason) + gain, abs=0.11)


def test_a_lead_too_loud_is_told_to_come_down():
    instru = beat(SECONDS)
    lead = _against(voice(SECONDS, seed=11), instru, 16.0)
    out = mix(_parts([("ch0", "Lead", "lead_vocal", lead, None)], [("g1", "Instru", "beat", instru)]),
              1.0, 95.0, {"ch0": "none"})
    gain, _ = _gain(out.parts[0])
    [warning] = out.warnings
    assert gain == -MAX_LEAD_CHANGE_DB and warning.endswith("baisse la voix ou monte l'instru dans FL Studio")
    assert _stays_at(warning) > engine.LEAD_BALANCE[2]


def test_other_voices_keep_their_4_db_limit_and_are_named_when_off_their_window():
    instru = beat(SECONDS)
    lead = _against(voice(SECONDS, seed=11), instru, 1.0)
    adlib = voice(SECONDS, seed=12, notes=[220, 247], level=0.01)  # far under the lead
    out = mix(_parts([("ch0", "Lead", "lead_vocal", lead, None), ("ch1", "Adlib", "adlib", adlib, None)],
                     [("g1", "Instru", "beat", instru)]), 1.0, 95.0, {"ch0": "none", "ch1": "none"})
    res = {p.key: p for p in out.parts}
    gain, reason = _gain(res["ch1"])
    assert gain == engine.MAX_LEVEL_CHANGE_DB
    [warning] = out.warnings  # the lead is in its window: only the ad-lib
    assert warning.startswith("« Adlib » reste à -") and warning.endswith(
        "de « Lead », niveau d'Eden compris (visé -6 dB, accepté de -9 à -3 dB) : monte cette voix dans FL Studio")
    assert _stays_at(warning) == pytest.approx(_before(reason) + gain, abs=0.11)


def test_a_double_that_copies_the_lead_is_kept_without_a_warning():
    instru = beat(SECONDS)
    lead = _against(voice(SECONDS, seed=11), instru, 1.0)
    out = mix(_parts([("ch0", "Lead", "lead_vocal", lead, None), ("ch1", "Double", "double", 0.05 * lead, None)],
                     [("g1", "Instru", "beat", instru)]), 1.0, 95.0, {"ch0": "none", "ch1": "none"})
    double = next(p for p in out.parts if p.key == "ch1")
    assert next(t.label for t in double.treatments if t.kind == "gain") == "Niveau gardé"
    assert out.warnings == []


# -- the bands carved for the words ---------------------------------------------------------------

def test_masking_bands_are_the_thirds_from_250_hz_to_8_khz():
    noise = np.random.default_rng(1).normal(0, 0.1, (int(4 * FS), 2))
    bands = band_masking(noise, 0.5 * noise, FS, np.ones(37, dtype=bool))
    centres = [math.sqrt(b.low_hz * b.high_hz) for b in bands]
    assert centres == pytest.approx([250 * 2 ** (i / 3) for i in range(16)])
    assert bands[0].low_hz == pytest.approx(222.7, abs=0.1) and bands[-1].high_hz == pytest.approx(8979.7, abs=0.1)
    weights = [SII_OCTAVE_WEIGHTS[o] / 3 for o in (250, 250, *[o for o in (500, 1000, 2000, 4000) for _ in "abc"],
                                                   8000, 8000)]
    assert [b.weight for b in bands] == pytest.approx(weights)
    assert max(b.voice_db for b in bands) == 0.0 and all(b.voice_db <= 0.0 for b in bands)
    assert all(b.masking_db == pytest.approx(-6.02, abs=0.01) for b in bands)


# instru − voice and voice level (re its strongest band) per third, 250 Hz … 8 kHz, measured by
# band_masking on the review's 80 s song at 44.1 kHz (lead +11 dB, Eden's 808 harmonics): the verifier's case
REVIEW_SONG = [(-3.2, 0.0), (-6.9, -1.2), (-8.0, -1.4), (-11.7, -0.2), (-15.7, -0.2), (-12.7, -2.4),
               (-8.7, -6.4), (-9.9, -6.1), (-7.9, -6.4), (-4.8, -7.7), (-2.9, -10.5), (-3.2, -11.9),
               (-1.4, -12.9), (-1.5, -11.2), (-1.3, -10.2), (-0.4, -9.8)]


def _thirds(values: list[tuple[float, float]]) -> list[BandMasking]:
    """Bands as band_masking gives them, from (instru − voice, voice re its strongest band) per third."""
    out = []
    for i, (masking, voice_db) in enumerate(values):
        fc = 250 * 2 ** (i / 3)
        weight = SII_OCTAVE_WEIGHTS[250 * 2 ** round(i / 3)] / 3
        out.append(BandMasking(fc / 2 ** (1 / 6), fc * 2 ** (1 / 6), masking, weight, voice_db))
    return out


def test_the_carve_keeps_the_bands_where_a_dip_makes_the_most_words_audible():
    chosen = engine._carve_bands(_thirds(REVIEW_SONG), 1.0)
    # in the 2 and 4 kHz octaves (2.2–5.7 kHz); the old ranking (weight × (masking + 3)) took 177–223 Hz
    # and 9–11.3 kHz on this song
    assert [round(b.low_hz) for b, _ in chosen] == [3564, 4490, 2245]
    assert [d for _, d in chosen] == pytest.approx([1 + 1.6 / 3, 1 + 1.5 / 3, 1 + 0.1 / 3])
    half = engine._carve_bands(_thirds(REVIEW_SONG), 0.5)  # the intensity scales the dip, not the choice
    assert [b.low_hz for b, _ in half] == [b.low_hz for b, _ in chosen]
    assert [d for _, d in half] == pytest.approx([d / 2 for _, d in chosen])


def test_the_carve_skips_bands_a_dip_cannot_uncover_and_bands_without_voice():
    values = [(-10.0, 0.0)] * 16
    values[9] = (14.0, -2.0)  # 2 kHz buried 14 dB deep: a 3 dB dip uncovers nothing
    values[6] = (0.0, -25.0)  # 1 kHz: the voice is 25 dB under its strongest band
    values[12] = (2.0, -5.0)  # 4 kHz
    values[3] = (12.0, -3.0)  # 500 Hz, 12 dB deep: still a candidate
    assert [round(b.low_hz) for b, _ in engine._carve_bands(_thirds(values), 1.0)] == [3564, 445]
    assert _thirds(values)[9].weight > _thirds(values)[12].weight > _thirds(values)[3].weight


def test_the_carve_reason_says_how_the_bands_were_chosen():
    instru = _keys(SECONDS) + _kicks(SECONDS)[0] + 3 * _hats(SECONDS) + 3 * _snare(SECONDS) + _808(SECONDS)
    lead = _against(voice(SECONDS, seed=11), instru, -2.0)
    out = mix(_parts([("ch0", "Lead", "lead_vocal", lead, None)], [("g1", "Instru", "beat", instru)]),
              1.0, 140.0, {"ch0": "none"})
    carve = next(t for t in out.parts[1].treatments if t.kind == "carve")
    bands = [(float(lo), float(hi)) for lo, hi in re.findall(r"(\d+)–(\d+) Hz", carve.label)]
    assert len(bands) == 3 and all(lo >= 222 and hi <= 8980 for lo, hi in bands)
    assert carve.reason.startswith("Bandes où un creux rend le plus de paroles audibles (importance de la bande "
                                   "pour les paroles × audibilité gagnée, ANSI S3.5)")
    assert "sans celles qu'elle couvre de plus de 12 dB (un creux de 3 dB n'y découvre rien) ni celles où la " \
        "voix est à plus de 20 dB sous sa bande la plus forte" in carve.reason


# -- the other voices' dip leaves their FL effects alone ------------------------------------------

def test_the_dip_of_an_other_voice_does_not_touch_its_fl_reverb(monkeypatch):
    dry = voice(12.0, seed=12, notes=[220, 247], level=0.15)
    wet = _fl_reverb(dry[:, 0], -10.0)
    dipped = []
    original = dsp.dip_band_when

    def spy(x, fs, envelope, size, depth_db, low_hz=1500.0, high_hz=4000.0):
        if (low_hz, high_hz) == (1000.0, 4000.0):
            dipped.append(x.copy())
        return original(x, fs, envelope, size, depth_db, low_hz, high_hz)

    monkeypatch.setattr(dsp, "dip_band_when", spy)
    for role in ("adlib", "back_vocal", "double"):
        dipped.clear()
        parts = _parts([("ch0", "Lead", "lead_vocal", voice(12.0, seed=11), None), ("ch1", "V", role, dry + wet, dry)],
                       [("g1", "Instru", "beat", beat(12.0))])
        out = mix(parts, 1.0, 95.0, {"ch0": "none", "ch1": "tracked"})
        dip = next(t for t in out.parts[1].treatments if t.kind == "dip")
        assert dip.reason.endswith("; tes reverbs et delays FL restent tels quels")
        [x] = dipped
        rest = slice(int(4.3 * FS), int(4.9 * FS))  # the voice is silent, its FL reverb rings
        assert np.sum(x[rest] ** 2) < 1e-6 * np.sum(wet[rest] ** 2)


# -- duplicated lead tracks -----------------------------------------------------------------------

def test_a_duplicated_lead_track_raises_the_first_and_keeps_the_copy():
    instru = beat(SECONDS)
    lead = _against(voice(SECONDS, seed=11), instru, -18.0)
    parts = _parts([("ch0", "Voix", "vocal", lead, None), ("ch1", "Voix (dupliquée)", "vocal", lead.copy(), None)],
                   [("g1", "Instru", "beat", instru)])
    out = mix(parts, 1.0, 95.0, {"ch0": "none", "ch1": "none"})
    res = {p.key: p for p in out.parts}
    gain, reason = _gain(res["ch0"])
    assert gain == MAX_LEAD_CHANGE_DB and "sauf « Voix (dupliquée) » (copie, jamais montée)" in reason
    kept = next(t for t in res["ch1"].treatments if t.kind == "gain")
    assert kept.label == "Niveau gardé" and kept.reason.startswith("Copie de « Voix » (corrélation 1.00)")
    # the copy was not raised: the stack is measured again, two equal voices, one 10 dB up
    [warning] = out.warnings
    assert warning.startswith("« Voix » + « Voix (dupliquée) », qui chantent ensemble, restent à -")
    assert _stays_at(warning) == pytest.approx(_before(reason) + 20 * math.log10((10 ** (gain / 20) + 1) / 2),
                                               abs=0.15)


def test_a_copy_that_comes_first_is_still_the_copy():
    instru = beat(SECONDS)
    lead = _against(voice(SECONDS, seed=11), instru, -8.0)
    copy = _sung_only(lead, 0.0, 4.0)  # an in-out copy only copies one way
    parts = _parts([("ch0", "Voix (copie)", "vocal", copy, None), ("ch1", "Voix", "vocal", lead, None)],
                   [("g1", "Instru", "beat", instru)])
    res = {p.key: p for p in mix(parts, 1.0, 95.0, {"ch0": "none", "ch1": "none"}).parts}
    assert _gain(res["ch1"])[0] > 0
    assert next(t.label for t in res["ch0"].treatments if t.kind == "gain") == "Niveau gardé"


# -- voices left in the rest of the mix -----------------------------------------------------------

def test_split_says_when_a_voice_is_left_in_the_rest_of_the_mix(tmp_path, monkeypatch):
    project = make_session(tmp_path)
    report = inspect_project(project, roots=SearchRoots())
    renders = render_project(project, sim_renderer(), timeout_s=120, report=report)
    assert not split(report, renders).voices_in_residual
    monkeypatch.setattr(plan, "MAX_VOCAL_JOBS", 1)  # the ad-lib gets no render of its own
    renders = render_project(project, sim_renderer(), timeout_s=120, report=report)
    parts = split(report, renders)
    assert [v.label for v in parts.voices] == ["Lead"] and parts.voices_in_residual


def test_with_voices_in_the_rest_of_the_mix_only_the_groups_are_measured_and_carved(monkeypatch):
    instru = _keys(SECONDS) + _kicks(SECONDS)[0] + _hats(SECONDS) + _snare(SECONDS)
    extra = voice(SECONDS, seed=13, level=0.2)  # a voice beyond the vocal renders, in the rest of the mix
    lead = _against(voice(SECONDS, seed=11), instru, -2.0)
    measured, dipped = [], []
    band_masking_, dip_band_when = engine.band_masking, dsp.dip_band_when

    def measure(vocal, other, fs, mask):
        measured.append(other)
        return band_masking_(vocal, other, fs, mask)

    def dip(x, fs, envelope, size, depth_db, low_hz=1500.0, high_hz=4000.0):
        dipped.append(x)
        return dip_band_when(x, fs, envelope, size, depth_db, low_hz, high_hz)

    monkeypatch.setattr(engine, "band_masking", measure)
    monkeypatch.setattr(dsp, "dip_band_when", dip)
    parts = _parts([("ch0", "Lead", "lead_vocal", lead, None)], [("g1", "Instru", "beat", instru)], residual=extra)
    for left in (False, True):
        measured.clear()
        dipped.clear()
        out = mix(Parts(parts.voices, parts.groups, parts.residual, FS, parts.premaster, voices_in_residual=left),
                  1.0, 140.0, {"ch0": "none"})
        [other] = measured
        expected = parts.groups[0].audio + (0 if left else extra)
        assert np.allclose(other, expected, rtol=0, atol=1e-9)
        assert any(x is parts.residual.audio for x in dipped) is not left
        res = {p.key: p for p in out.parts}
        carve = next(t for t in res["g1"].treatments if t.kind == "carve")
        note = "; des voix sont restées dans le reste du mix : seuls les groupes sont mesurés et creusés"
        assert carve.reason.endswith(note) is left
    assert "residual" not in res  # with voices in it, the rest of the mix is neither carved nor shown carved
