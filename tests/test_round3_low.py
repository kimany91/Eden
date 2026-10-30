"""Third review round on the low end and the reverb ceiling, checked by measurement: the 808's
notes evened out at the mix on the bass groups, where the kicks FL renders apart do not get in the
way (not when FL already ducks the 808 at each kick), no low-band compressor left at the master,
and the FL effects of a voice set on one side taken out of the dry mix exactly as they are in it."""

import re

import numpy as np
import pytest

from eden.mix import dsp, engine, lowend, stereo
from eden.mix import master as M
from eden.mix.engine import mix
from synth_voice import FS, beat, voice
from test_engine_mix import _fl_reverb, _parts

BEAT_S = 60 / 140  # 140 BPM
SECONDS = 20.0
EVENING = "Tenue des notes du 808"
RETURNS_SCALE, PLACE = engine.returns_scale, stereo.place  # spied on, one mix at a time


def _808(fs, every_s, tau_s=0.6, vary_db=0.0, pitches=(43.65, 51.91, 58.27, 38.89), seed=0):
    """Sine 808 notes every ``every_s`` (3 ms attack, 10 ms release), decaying with ``tau_s``
    (None: held), each one up to ``vary_db`` louder or quieter than the others."""
    rng = np.random.default_rng(seed)
    out = np.zeros(int(SECONDS * fs))
    for i, start_s in enumerate(np.arange(0, SECONDS - 1, every_s)):
        start = int(start_s * fs)
        t = np.arange(min(out.size - start, int(every_s * fs))) / fs
        env = (np.exp(-t / tau_s) if tau_s else np.ones(t.size)) * np.minimum(1, t / 0.003)
        env[-int(0.01 * fs):] *= np.linspace(1, 0, int(0.01 * fs))
        level = 10 ** (rng.uniform(-vary_db, vary_db) / 20)
        out[start:start + t.size] += level * env * np.sin(2 * np.pi * pitches[i % len(pitches)] * t)
    return np.stack([0.35 * out] * 2, 1)


def _count(every_s):
    return np.arange(0, SECONDS - 1, every_s).size


def _legato(fs, vary_db, seed=0):
    """Held notes on one pitch (49 Hz), back to back: each one stops in 200 samples and the next
    starts at once, at its own level."""
    rng = np.random.default_rng(seed)
    out = np.zeros(int(SECONDS * fs))
    note = int(0.857 * fs)
    t = np.arange(note) / fs
    for start in range(0, out.size - note, note):
        env = np.ones(note)
        env[-200:] = np.linspace(1, 0, 200)
        out[start:start + note] = 10 ** (rng.uniform(-vary_db, vary_db) / 20) * env * np.sin(2 * np.pi * 49 * t)
    return np.stack([0.35 * out] * 2, 1)


UNEVEN = {  # notes up to 4 dB louder or quieter than the others
    "decaying": lambda fs: _808(fs, 2 * BEAT_S, 0.6, 4.0),
    "held-legato-same-pitch": lambda fs: _legato(fs, 4.0),
    "fast-every-0.21s-same-pitch": lambda fs: _808(fs, 0.214, 0.6, 4.0, pitches=(49.0,)),
    "held-pitch-changes": lambda fs: _808(fs, 2 * BEAT_S, None, 4.0),
}


def _kick_starts(fs):
    """Beats 1, 1¾, 2½, 3½ and 4¼ of every bar (samples)."""
    return [int((bar + b * BEAT_S) * fs) for bar in np.arange(0, SECONDS - 1, 4 * BEAT_S)
            for b in (0, 0.75, 1.5, 2.5, 3.25)]


def _kicks(fs, level):
    """Kicks (pitch falling from 120 to 50 Hz) on ``_kick_starts``: some land on an 808 note's
    attack, the others on its tail."""
    t = np.arange(int(0.3 * fs)) / fs
    kick = np.sin(2 * np.pi * np.cumsum(50 + 70 * np.exp(-t / 0.03)) / fs) * np.exp(-t / 0.12)
    out = np.zeros(int(SECONDS * fs))
    for start in _kick_starts(fs):
        if start + kick.size < out.size:
            out[start:start + kick.size] += kick
    return np.stack([level * out] * 2, 1)


def _sidechained(bass, fs, depth_db=6.0, release_s=0.15):
    """``bass`` ducked in FL at each kick (a sidechain): ``depth_db`` down in 5 ms, then back up
    with a ``release_s`` time constant."""
    gain_db = np.zeros(bass.shape[0])
    t = np.arange(int(1.5 * fs)) / fs
    shape = -depth_db * np.where(t < 0.005, t / 0.005, np.exp(-(t - 0.005) / release_s))
    for start in _kick_starts(fs):
        span = gain_db[start:start + t.size]
        span[:] = np.minimum(span, shape[:span.size])
    return bass * 10 ** (gain_db[:, None] / 20)


def _song(fs, bass, kick_level=0.45):
    """The 808 on its own group, the kicks on a drum group as FL renders them."""
    groups = [("g1", "Kick", "drums", _kicks(fs, kick_level))] if kick_level else []
    return _parts([], [*groups, ("g2", "808", "bass", bass)], fs=fs)


def _heads(bass, fs):
    low = dsp.split_band(bass, fs, None, lowend.CROSSOVER_HZ)[0]
    return lowend.note_heads(low, fs, lowend.track_bass(bass, fs))


def _spread(heads):
    levels = [h.level_db for h in heads]
    return float(np.percentile(levels, 90) - np.percentile(levels, 10))


def _evening(result):
    return next((t for t in result.treatments if t.label.startswith(EVENING)), None)


@pytest.fixture
def evened(monkeypatch):
    """What ``lowend.even_notes`` returned in the mix."""
    seen = []
    real = lowend.even_notes
    monkeypatch.setattr(lowend, "even_notes", lambda *a, **kw: seen.append(real(*a, **kw)) or seen[-1])
    return seen


# -- L1: the 808's notes, read on the bass groups ---------------------------------------------------

@pytest.mark.parametrize("fs", [44100, 48000])
@pytest.mark.parametrize("tau_s", [0.3, 0.6, 1.5])
@pytest.mark.parametrize("beats", [1, 2, 4])
def test_equal_decaying_808_notes_are_read_one_by_one_and_equal(fs, tau_s, beats):
    heads = _heads(_808(fs, beats * BEAT_S, tau_s), fs)
    assert len(heads) == _count(beats * BEAT_S)  # every note, the first of the song too
    assert _spread(heads) < 1.0  # a note's own decay is not a difference between notes


@pytest.mark.parametrize("fs", [44100, 48000])
@pytest.mark.parametrize("case", UNEVEN)
def test_uneven_808_notes_are_read_as_uneven(fs, case):
    heads = _heads(UNEVEN[case](fs), fs)
    assert len(heads) >= 8 and _spread(heads) > lowend.EVEN_SPREAD_DB


def test_a_slide_goes_on_with_its_note():
    # F1 sliding down to C1 on a decaying 808: the C1 after the slide has no attack of its own, only
    # the note's decay, and is not compared with the attacks
    bars = []
    for _ in range(16):
        f = np.concatenate([np.full(int(0.3 * FS), 43.65), np.geomspace(43.65, 32.70, int(0.2 * FS)),
                            np.full(int(0.5 * FS), 32.70)])
        t = np.arange(f.size) / FS
        bars += [0.35 * np.exp(-t / 0.6) * np.minimum(1, t / 0.003) * np.sin(2 * np.pi * np.cumsum(f) / FS),
                 np.zeros(int(0.1 * FS))]
    mono = np.concatenate(bars)
    heads = _heads(np.stack([mono, mono], 1), FS)
    assert len(heads) == 16 and _spread(heads) < 0.5


def test_notes_late_in_a_song_are_read_where_they_are_at_44_1_khz():
    # a 1 ms frame is 44 samples at 44.1 kHz (0.998 ms): read as 1 ms, a note 90 s in would be looked
    # for 0.2 s after it, here in the silence after the note
    x = np.zeros(100 * FS)
    t = np.arange(int(0.25 * FS)) / FS
    note = 0.35 * np.minimum(1, t / 0.003) * np.minimum(1, (t[-1] - t) / 0.01) * np.sin(2 * np.pi * 49 * t)
    for start_s in (90, 92, 94, 96, 98):
        x[start_s * FS:start_s * FS + note.size] += note
    heads = _heads(np.stack([x, x], 1), FS)
    assert FS == 44100 and [round(h.start_s) for h in heads] == [90, 92, 94, 96, 98]
    assert all(-0.03 < h.start_s - round(h.start_s) <= 0.0 for h in heads)  # on the attack, not after it
    assert _spread(heads) < 0.1


def test_notes_above_80_hz_are_not_compared():
    # equal notes on 45 and 110 Hz: the band under 100 Hz keeps less of the 110 Hz ones, which would
    # read more than 4 dB quieter than they are
    x = _808(FS, 2 * BEAT_S, 0.6, pitches=(45.0, 110.0))
    level = [10 * np.log10(np.mean(dsp.split_band(_808(FS, 2 * BEAT_S, 0.6, pitches=(f,)), FS, None,
                                                  lowend.CROSSOVER_HZ)[0] ** 2)) for f in (45.0, 110.0)]
    assert level[0] - level[1] > lowend.EVEN_SPREAD_DB
    heads = _heads(x, FS)
    assert len(heads) == (_count(2 * BEAT_S) + 1) // 2 and _spread(heads) < 0.5  # the 45 Hz notes only
    assert lowend.even_notes(x, FS, lowend.track_bass(x, FS), 1.0) is None


# -- L1: in the mix ---------------------------------------------------------------------------------

@pytest.mark.parametrize("fs, kick_level", [(44100, 0.45), (48000, 0.1)])  # kicks louder than the 808, quieter
@pytest.mark.parametrize("tau_s", [0.3, 0.6, 1.5])
@pytest.mark.parametrize("beats", [1, 2, 4])
def test_equal_808_notes_are_left_alone_whatever_the_kicks_do(fs, kick_level, tau_s, beats, evened):
    out = mix(_song(fs, _808(fs, beats * BEAT_S, tau_s), kick_level), 1.0, 140.0, {})
    res = {p.key: p for p in out.parts}
    assert evened == [None] and _evening(res["g2"]) is None
    assert not any(t.kind == "compressor" for p in out.parts for t in p.treatments)


@pytest.mark.parametrize("fs", [44100, 48000])
@pytest.mark.parametrize("case", ["decaying", "held-legato-same-pitch", "fast-every-0.21s-same-pitch"])
def test_uneven_808_notes_are_evened_on_the_808_group_and_say_so(fs, case, evened):
    bass = UNEVEN[case](fs)
    out = mix(_song(fs, bass), 1.0, 140.0, {})
    res = {p.key: p for p in out.parts}
    [e] = evened
    t = _evening(res["g2"])
    assert t.label == "Tenue des notes du 808 2.0:1 sous 100 Hz" and t.kind == "compressor"
    assert [x.kind for x in res["g2"].treatments][:2] == ["compressor", "duck"]  # evened, then ducked
    assert _evening(res["g1"]) is None  # the kicks are not touched
    # the reason's numbers: the notes read on the 808 alone, as without the kicks
    heads = _heads(bass, fs)
    shown = re.search(r"^Les (\d+) notes du 808 varient de (\d+\.\d) dB d'une note à l'autre", t.reason)
    assert shown and int(shown.group(1)) == len(e.heads) == len(heads)
    assert float(shown.group(2)) == pytest.approx(_spread(heads), abs=0.051) and _spread(heads) > 4.0
    assert ("Seuil 3.0 dB sous la note du 90e centile, soit 1.5 dB de réduction sur elle (courbe du "
            "compresseur), 3.0 dB au plus, attaque 10 ms, relâchement 150 ms") in t.reason
    assert "même gain" not in t.reason  # one 808 group
    assert t.params["threshold_db"] == e.threshold_db and 0.3 < t.measured["reduction_max_db"] <= 3.0


@pytest.mark.parametrize("k", [1.0, 0.5, 0.35])
def test_the_90th_percentile_note_gets_1_5_dB_times_k_on_the_compressor_curve(k):
    bass = UNEVEN["decaying"](FS)
    e = lowend.even_notes(bass, FS, lowend.track_bass(bass, FS), k)
    assert e.ratio == 1 + k and -e.gain_db.min() <= 3.0 * k + 1e-9
    assert e.p90_db == pytest.approx(np.percentile([h.detector_db for h in e.heads], 90))
    # the compressor's own curve, soft knee included, on a steady level at that 90th percentile
    steady = np.full(FS, 10 ** (e.p90_db / 20))
    curve, _ = dsp.compressor_gain_db(steady, FS, e.threshold_db, e.ratio, attack_ms=lowend.EVEN_ATTACK_MS,
                                      release_ms=lowend.EVEN_RELEASE_MS, knee_db=lowend.EVEN_KNEE_DB)
    assert -curve[500] == pytest.approx(1.5 * k, abs=1e-3)
    # what the 10 ms attack leaves of it on that note's head, as applied
    det = np.array([h.detector_db for h in e.heads])
    p90 = e.heads[int(np.argsort(det)[int(round(0.9 * (det.size - 1)))])]
    first = int(round(p90.start_s * FS / e.frame))
    assert 0.65 * 1.5 * k < -e.gain_db[first:first + lowend.NOTE_HEAD_MS].min() <= 1.5 * k


def test_a_reduction_that_does_not_move_0_3_dB_is_not_applied():
    # as for the voices: at 20 %, the loudest notes would lose under 0.3 dB more than the rest
    bass = UNEVEN["decaying"](FS)
    assert lowend.even_notes(bass, FS, lowend.track_bass(bass, FS), 0.2) is None


def test_every_808_group_gets_the_same_gain(evened, monkeypatch):
    bass = UNEVEN["decaying"](FS)
    calls = []
    real = lowend.apply_low_gain
    monkeypatch.setattr(lowend, "apply_low_gain", lambda x, fs, e: calls.append((x, e, real(x, fs, e))) or calls[-1][2])
    parts = _parts([], [("g1", "808", "bass", 0.7 * bass), ("g2", "Sub", "bass", 0.3 * bass)])
    out = mix(parts, 1.0, 140.0, {})
    [e] = evened
    assert len(calls) == 2 and calls[0][1] is calls[1][1] is e  # computed once, on their sum
    # linear: each group gets the gain on its own band below 100 Hz, their sum gets exactly that gain
    summed = calls[0][2] + calls[1][2]
    assert np.allclose(summed, real(calls[0][0] + calls[1][0], FS, e), atol=1e-6)
    assert np.allclose(calls[0][2] / 0.7, calls[1][2] / 0.3, atol=1e-5)
    for p in out.parts:
        assert _evening(p).reason.endswith("; le même gain sur chaque groupe 808")


@pytest.mark.parametrize("fs", [44100, 48000])
def test_at_0_the_808_groups_come_back_bit_exact(fs, evened):
    bass = UNEVEN["decaying"](fs)
    parts = _song(fs, bass)
    out = mix(parts, 0.0, 140.0, {})
    assert np.array_equal(out.premaster, parts.premaster) and evened == []
    assert not any(p.treatments for p in out.parts)
    assert lowend.even_notes(bass, fs, lowend.track_bass(bass, fs), 0.0) is None


def test_a_beat_in_one_file_gets_no_808_evening(evened):
    # the documented limit: no 808 group, no notes to read apart from the kicks
    parts = _parts([], [("g1", "Instru", "beat", _kicks(FS, 0.45) + UNEVEN["decaying"](FS))])
    out = mix(parts, 1.0, 140.0, {})
    assert evened == [] and not any(_evening(p) for p in out.parts)


@pytest.mark.parametrize("fs", [44100, 48000])
def test_an_808_that_fl_already_ducks_at_each_kick_is_not_evened(fs, evened):
    # equal notes ducked by 6 dB at each kick in FL (a sidechain): read alone, its dips and its climbs
    # back pass for many more notes than there are, and very uneven ones
    bass = _sidechained(_808(fs, 2 * BEAT_S, 0.6), fs)
    heads = _heads(bass, fs)
    assert len(heads) > 2 * _count(2 * BEAT_S) and _spread(heads) > 3 * lowend.EVEN_SPREAD_DB
    assert lowend.even_notes(bass, fs, lowend.track_bass(bass, fs), 1.0) is not None
    # the mix measures that duck on the kicks rendered apart: the 808's notes are left as they are
    evened.clear()
    out = mix(_song(fs, bass), 1.0, 140.0, {})
    assert evened == [] and not any(_evening(p) for p in out.parts)
    assert not any(t.kind in ("compressor", "duck") for p in out.parts for t in p.treatments)


def test_the_master_no_longer_evens_the_low_band():
    sub = UNEVEN["decaying"](FS)
    above = dsp.split_band(beat(SECONDS, level=0.2), FS, 150, None)[0]  # the 808 alone under 100 Hz
    r = M.master(above + sub, FS, 1.0, tempo_bpm=140)
    assert all(t.label.startswith("Compression de bus") for t in r.treatments if t.kind == "compressor")
    assert not hasattr(M, "_note_peaks_db") and not hasattr(lowend, "periodicity")


# -- L2: the reverb ceiling's dry mix -----------------------------------------------------------------

def _voices(back_level=0.08, back_wet_gain=1.0, seconds=12.0):
    """A lead, a back vocal alone (set 40 % to the right) and an ad-lib (changing side), both with an
    FL reverb rendered apart."""
    back = voice(seconds, seed=12, notes=[220, 247], level=back_level)
    adlib = voice(seconds, seed=13, notes=[196, 233], level=0.08)
    back_wet, adlib_wet = back_wet_gain * _fl_reverb(back[:, 0], -8.0), _fl_reverb(adlib[:, 0], -8.0)
    return _parts([("ch0", "Lead", "lead_vocal", voice(seconds, seed=11), None),
                   ("ch1", "Chœur", "back_vocal", back + back_wet, back),
                   ("ch2", "Adlib", "adlib", adlib + adlib_wet, adlib)],
                  [("g1", "Instru", "beat", beat(seconds))])


def _parts_wet(parts, key):
    """The FL effects of the voice ``key``, as Eden reads them."""
    return next(v.space for v in parts.voices if v.key == key).astype(np.float64)


def _ceiling_inputs(monkeypatch, parts):
    """(the FL effects and the dry mix the reverb ceiling measured, the FL effects each placed
    voice was given with its placement, the result)."""
    seen, placed = {}, []

    def scale(fl_wet, returns, dry, fs, ceiling):
        seen.update(fl_wet=fl_wet.copy(), dry=dry.copy())
        return RETURNS_SCALE(fl_wet, returns, dry, fs, ceiling)

    def place(x, fs, p, effects=None):
        if effects is not None:
            placed.append((p, effects.copy()))
        return PLACE(x, fs, p, effects)

    monkeypatch.setattr(engine, "returns_scale", scale)
    monkeypatch.setattr(stereo, "place", place)
    out = mix(parts, 1.0, 95.0, {"ch0": "none", "ch1": "tracked", "ch2": "tracked"})
    return seen, placed, out


def test_the_reverb_ceiling_counts_the_fl_effects_where_the_placement_put_them(monkeypatch):
    parts = _voices(back_level=0.6)  # loud enough to drown the lead: brought down (never raised)
    seen, placed, out = _ceiling_inputs(monkeypatch, parts)
    assert [(p.key, p.position, p.alternate) for p, _ in placed] == [("ch1", 0.4, False), ("ch2", 0.5, True)]
    res = {p.key: p for p in out.parts}
    assert res["ch1"].level_change_db < -1.0
    back, adlib = (_parts_wet(parts, key) for key in ("ch1", "ch2"))
    # the effects each voice was placed with are its FL effects after its level change...
    for (_, effects), wet, key in zip(placed, (back, adlib), ("ch1", "ch2"), strict=True):
        assert np.allclose(effects, wet * 10 ** (res[key].level_change_db / 20), atol=1e-6)
    # ...and the ceiling takes out of the dry mix what is in it: moved to the side of the voice set
    # on one side, left where FL put them under the ad-lib that changes side
    expected = stereo.balance(placed[0][1], 0.4) + placed[1][1]
    assert np.allclose(seen["fl_wet"], expected, atol=1e-9)


def test_the_dry_mix_holds_none_of_the_fl_effects_of_a_voice_set_on_one_side(monkeypatch):
    # the back vocal's FL reverb twice as loud: the dry mix the ceiling measures does not move
    parts = _voices()
    first, _, a = _ceiling_inputs(monkeypatch, parts)
    second, _, b = _ceiling_inputs(monkeypatch, _voices(back_wet_gain=2.0))
    assert all(p.level_change_db == 0.0 for p in [*a.parts, *b.parts])  # no level change: same chains
    assert np.allclose(first["dry"], second["dry"], atol=1e-6)
    wet = _parts_wet(parts, "ch1")
    assert np.allclose(second["fl_wet"] - first["fl_wet"], stereo.balance(wet, 0.4), atol=1e-6)
