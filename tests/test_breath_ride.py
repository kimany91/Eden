"""What a user heard and reported, fixed at the root (mix/breath.py, mix/riding.py, mix/space.py):
breaths were raised by the chain and by the rider, phrases moved without a cause in the signal, and
Eden stacked its space onto takes that already carry a printed reverb."""

import math

import numpy as np
from types import SimpleNamespace

from eden.mix import riding
from eden.mix.analysis import measure_vocal
from eden.mix.breath import find_breaths, sung_activity
from eden.mix.session import fl_space_status
from eden.mix.space import RECORDED_RING_DB, ReverbDesign, design_space, recorded_space, reverb
from eden.mix.treatments import apply
from eden.mix.vocal import plan_voice
from synth_voice import FS, beat, voice



def _rms_db(x: np.ndarray, a: float, b: float) -> float:
    seg = x[int(a * FS):int(b * FS)]
    return 10 * math.log10(float(np.mean(seg ** 2)) + 1e-20)


BREATH = (4.55, 4.8)  # where synth_voice puts a breath (0.5 s before each phrase)
SUNG = (1.0, 3.5)


def test_breaths_are_found_and_brought_down_before_compression():
    v = voice(30, seed=3, breaths=0.25)
    found = find_breaths(v, FS)
    assert 4 <= found.count <= 6 and found.deepest_db > 3.0
    assert find_breaths(voice(30, seed=3), FS).count == 0  # a clean voice: nothing invented

    m = measure_vocal(v, FS)
    treatments = plan_voice(m, "lead_vocal", 1.0, False)
    assert treatments[0].kind == "breath"  # first: everything after raises what is left loud
    y = apply(v, FS, treatments, input_lufs=m.loudness_lufs)
    breath_treatment = next(t for t in treatments if t.kind == "breath")
    assert breath_treatment.applied and "respiration" in breath_treatment.label
    assert _rms_db(y, *BREATH) < _rms_db(v, *BREATH) - 3.0  # the breath goes down
    assert abs(_rms_db(y, *SUNG) - _rms_db(v, *SUNG)) < 0.5  # the words do not

    # without the stage, the same chain raises the breath: the bug the user heard
    rest = [t for t in plan_voice(m, "lead_vocal", 1.0, False) if t.kind != "breath"]
    raised = apply(v, FS, rest, input_lufs=m.loudness_lufs)
    assert _rms_db(raised, *BREATH) > _rms_db(v, *BREATH) + 1.0


def test_the_rider_never_takes_a_breath_for_a_phrase():
    v, b = voice(30, seed=3, breaths=0.25), beat(30)
    sung, _, _ = sung_activity(v, FS)
    assert not sung[int(BREATH[0] / 0.001):int(BREATH[1] / 0.001)].any()  # voiced band: breaths stay out
    r = riding.ride(v, b, FS, 95.0, 1.0)
    assert len(r.phrases) == 6  # the six sung phrases, no phrase formed on a breath
    assert all(p.end_s - p.start_s > 2.0 for p in r.phrases)
    at_breath = 20 * math.log10(float(r.gain[int(4.6 * FS)]))
    held = r.phrases[0].gain_db  # the gain holds through the rest, it never jumps up on the breath
    assert at_breath <= max(held, 0.0) + 0.05


def test_every_ride_needs_its_cause_and_stays_small():
    sig = voice(30, seed=7, phrase_spread_db=8)
    r = riding.ride(sig, beat(30), FS, 95.0, 1.0)
    assert r.moved >= 1 and r.max_change_db <= riding.MAX_RIDE_DB == 3.0
    # a phrase is raised only as far as the voice dropped plus the beat rose: never more than its cause
    _, voice_db, beat_db, _ = riding.phrase_levels(sig, beat(30), FS, 95.0)
    v_med, b_med = float(np.median(voice_db)), float(np.median(beat_db))
    for p, v_db, b_db in zip(r.phrases, voice_db, beat_db, strict=True):
        if p.gain_db > 0:
            assert p.gain_db <= max(0.0, v_med - v_db) + max(0.0, b_db - b_med) + 1e-6


def test_a_take_with_a_printed_reverb_gets_no_space_on_top():
    dry = voice(30, seed=4)
    wet = dry + reverb(dry, FS, ReverbDesign(1.2, 20.0)) * 10 ** (-14 / 20)
    assert recorded_space(dry, FS) < RECORDED_RING_DB  # digital silence between phrases
    assert recorded_space(wet, FS) > RECORDED_RING_DB  # the recording itself rings

    def parts(audio):
        return SimpleNamespace(sample_rate=FS, voices=[
            SimpleNamespace(key="ch0", channels=[0], dry=None, audio=audio)])

    report = SimpleNamespace(sources=[SimpleNamespace(channel=0, space_effects=[])])
    assert fl_space_status(report, parts(wet)) == {"ch0": "printed"}
    assert fl_space_status(report, parts(dry)) == {"ch0": "none"}


def test_rap_space_stays_dry():
    sends = {s.name: s for s in design_space(95.0, "lead_vocal", 1.0).sends}
    assert sends["ambience"].level_db == -26.0 and sends["plate"].level_db == -23.0
    assert sends["delay"].level_db == -25.0 and sends["throw"].level_db == -16.0
    assert sends["throw"].feedback == 0.3


def _phrases_at(levels_db: list[float], seconds_each: float = 2.5, rest_s: float = 1.0) -> np.ndarray:
    """Phrases of one voice at the given levels, separated by silences."""
    out = []
    for i, db in enumerate(levels_db):
        seg = voice(seconds_each + 1, seed=10 + i, phrase_spread_db=0)[:int(seconds_each * FS)]
        out.append(seg * 10 ** (db / 20))
        out.append(np.zeros((int(rest_s * FS), 2)))
    return np.concatenate(out)


def test_a_phrase_the_artist_dropped_is_never_raised():
    sig = _phrases_at([0, 0, -8.0, 0, 0, -3.0, 0])  # -8: soft rap on purpose; -3: a take to even out
    r = riding.ride(sig, beat(sig.shape[0] / FS), FS, 95.0, 1.0)
    assert len(r.phrases) == 7
    assert r.phrases[2].gain_db == 0.0  # the 8 dB drop is a performance choice
    assert r.phrases[5].gain_db > 0.5  # the small drop is evened out


def test_every_voice_follows_the_one_ride_of_the_leads(monkeypatch):
    from eden.mix import engine
    from eden.mix.engine import mix
    from test_engine_mix import _parts

    rides = []
    apply_ride = engine.apply_ride
    monkeypatch.setattr(engine, "apply_ride", lambda x, r: rides.append(r) or apply_ride(x, r))
    # phrase offsets big enough to survive the chain's own leveling: what is left is ridden
    lead = _phrases_at([0, 8.0, 0, -5.0, 0, 8.0, 0])
    double = 0.5 * lead
    n = lead.shape[0]
    out = mix(_parts([("ch0", "Lead", "lead_vocal", lead, None), ("ch1", "Double", "double", double, None)],
                     [("g1", "Instru", "beat", beat(n / FS)[:n])]), 1.0, 95.0, {"ch0": "none", "ch1": "none"})
    res = {p.key: p for p in out.parts}
    assert res["ch0"].ride["moved"] >= 1 and res["ch1"].ride.get("follows") is True
    assert res["ch1"].ride["moved"] == res["ch0"].ride["moved"]
    assert len({id(r) for r in rides}) == 1  # one gain for the whole vocal performance
    assert any("garde l'équilibre" in t.reason for t in res["ch1"].treatments if t.kind == "ride")

