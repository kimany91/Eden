"""The mix engine on real-world project layouts: several drum and 808 inserts, a full beat next
to effects, tuned-down beats, voices that sing together or not, FL effects that stay in a voice,
a beat that shares a bus with the voices, very short songs."""

import math
import re

import numpy as np
import pytest
from scipy.signal import butter, oaconvolve, sosfilt

from eden.gui import viewmodel
from eden.mix import engine, lowend, stereo
from eden.mix.analysis import balance_against, level_of
from eden.mix.engine import analyse_song, mix
from eden.mix.loudness import integrated_loudness
from eden.mix.parts import Part, Parts
from eden.mix.tonality import bass_pitch_classes, detect_key, tuning
from synth_voice import FS, beat, voice
from test_blocks import MINOR_LOOP, _chords_only, _tone

BAR_S = 60 / 140 * 4  # one bar at 140 BPM
A_MINOR = [[57, 60, 64, 69], [53, 57, 60, 65], [48, 52, 55, 60], [55, 59, 62, 67]]  # Am F C G
A_MINOR_ROOTS = [33, 29, 36, 31]  # A1 F1 C2 G1
KICK_EVERY_S = BAR_S / 4


def _hz(midi: float, a4: float = 440.0) -> float:
    return a4 * 2 ** ((midi - 69) / 12)


def _stereo(x: np.ndarray) -> np.ndarray:
    return np.stack([x, x], axis=1)


def _keys(seconds: float, a4: float = 440.0, chords=A_MINOR) -> np.ndarray:
    """A chord per bar, each chord struck twice, piano-like decaying partials."""
    n, half = int(seconds * FS), int(BAR_S / 2 * FS)
    t = np.arange(half) / FS
    out = np.zeros(n)
    for bar, start in enumerate(range(0, n, 2 * half)):
        for midi in chords[bar % len(chords)]:
            f = _hz(midi, a4)
            note = 0.15 * sum(np.sin(2 * np.pi * h * f * t) / h ** 1.2 * np.exp(-t * (1.5 + 0.6 * h))
                              for h in range(1, 9) if h * f < FS / 2)
            for s in (start, start + half):
                if s < n:
                    out[s:s + half] += note[:n - s]
    return _stereo(out)


def _808(seconds: float, roots=A_MINOR_ROOTS, a4: float = 440.0) -> np.ndarray:
    """A bare sine 808, one note per bar."""
    n, bar = int(seconds * FS), int(BAR_S * FS)
    t = np.arange(bar) / FS
    out = np.zeros(n)
    for i, start in enumerate(range(0, n, bar)):
        note = 0.5 * np.sin(2 * np.pi * _hz(roots[i % len(roots)], a4) * t) * np.exp(-t / 1.2)
        out[start:start + bar] = note[:n - start]
    return _stereo(out)


def _kicks(seconds: float) -> tuple[np.ndarray, int]:
    """Four kicks a bar (a pitched-down sine thump) and how many there are."""
    n = int(seconds * FS)
    t = np.arange(int(0.3 * FS)) / FS
    thump = 0.6 * np.sin(2 * np.pi * np.cumsum(50 + 100 * np.exp(-t / 0.02)) / FS) * np.exp(-t / 0.08)
    starts = np.arange(0.2, seconds - 0.3, KICK_EVERY_S)
    out = np.zeros(n)
    for s in starts:
        out[int(s * FS):int(s * FS) + thump.size] += thump
    return _stereo(out), starts.size


def _hats(seconds: float) -> np.ndarray:
    n = int(seconds * FS)
    noise = sosfilt(butter(4, 7000, btype="highpass", fs=FS, output="sos"), np.random.default_rng(3).normal(0, 1, n))
    gate = (np.arange(n) % int(KICK_EVERY_S / 4 * FS)) < int(0.03 * FS)
    return _stereo(0.15 * noise * gate)


def _snare(seconds: float) -> np.ndarray:
    n = int(seconds * FS)
    t = np.arange(int(0.2 * FS)) / FS
    hit = (np.random.default_rng(5).normal(0, 0.6, t.size) + np.sin(2 * np.pi * 190 * t)) * np.exp(-t / 0.05)
    out = np.zeros(n)
    for s in np.arange(KICK_EVERY_S, seconds - 0.2, 2 * KICK_EVERY_S):
        out[int(s * FS):int(s * FS) + hit.size] += hit
    return _stereo(0.4 * sosfilt(butter(2, 150, btype="highpass", fs=FS, output="sos"), out))


def _parts(voices, groups, residual=None, fs: int = FS) -> Parts:
    """Parts from (key, label, role, audio, dry) voices and (key, label, role, audio) groups;
    ``residual`` is what the pre-master holds beside them."""
    n = max(a.shape[0] for *_, a in [*(v[:4] for v in voices), *groups])
    rest = np.zeros((n, 2)) if residual is None else residual
    vs = [Part(k, label, role, audio.astype(np.float32), [i], dry=None if dry is None else dry.astype(np.float32))
          for i, (k, label, role, audio, dry) in enumerate(voices)]
    gs = [Part(k, label, role, audio.astype(np.float32), [100 + i]) for i, (k, label, role, audio) in enumerate(groups)]
    premaster = rest + sum((p.audio.astype(np.float64) for p in vs + gs), np.zeros((n, 2)))
    return Parts(vs, gs, Part("residual", "Reste du mix (bus partagés, autres sources)", "residual", rest), fs,
                 premaster)


def _gain_db(result) -> float:
    return next((t.params["gain_db"] for t in result.treatments if t.kind == "gain"), 0.0)


# -- the song -------------------------------------------------------------------------------

def test_kicks_come_from_every_drum_insert_and_every_808_layer_ducks(monkeypatch):
    seconds = 12.0
    kicks, count = _kicks(seconds)
    bass = _808(seconds)
    # FL renders each drum on its own insert, in insert order: the hats come first
    groups = [("g1", "Hats", "drums", _hats(seconds)), ("g2", "Snare", "drums", _snare(seconds)),
              ("g3", "Kick", "drums", kicks), ("g4", "808", "bass", 0.7 * bass), ("g5", "Sub", "bass", 0.3 * bass),
              ("g6", "Keys", "music", _keys(seconds))]
    ducked = []
    duck_low_band = lowend.duck_low_band
    monkeypatch.setattr(lowend, "duck_low_band", lambda x, fs, hits, depth: ducked.append(hits.size) or
                        duck_low_band(x, fs, hits, depth))
    out = mix(_parts([], groups), 1.0, 140.0, {})
    res = {p.key: p for p in out.parts}
    assert out.song.kick_overlap > 0.5
    assert len(ducked) == 2 and all(abs(hits - count) <= 1 for hits in ducked)  # both layers, on the kicks only
    for key in ("g4", "g5"):
        duck = next(t for t in res[key].treatments if t.kind == "duck")
        assert duck.label == f"808 baissé de 3.0 dB sous 100 Hz à chaque kick ({ducked[0]} kicks)"


def test_a_single_drum_or_808_group_is_read_without_a_copy():
    kick = Part("g1", "Kick", "drums", np.zeros((10, 2), np.float32), [100])
    assert engine._sum_of([kick], "drums") is kick.audio and engine._sum_of([kick], "bass") is None


def _riser(seconds: float) -> np.ndarray:
    n, length = int(seconds * FS), int(3 * FS)
    rng = np.random.default_rng(9)
    out = np.zeros(n)
    for start in range(0, n - length, int(13.7 * FS)):
        noise = sosfilt(butter(2, [800, 6000], btype="bandpass", fs=FS, output="sos"), rng.normal(0, 0.1, length))
        out[start:start + length] += noise * np.arange(length) / length
    return _stereo(out)


def test_the_key_is_read_on_the_full_beat_when_effects_sit_beside_it():
    seconds = 16.0
    instru = _keys(seconds) + _kicks(seconds)[0] + _hats(seconds) + _snare(seconds)  # a 2-track in A minor
    groups = [("g1", "Instru", "beat", instru), ("g2", "808", "bass", _808(seconds)),
              ("g3", "Riser", "fx", _riser(seconds))]
    song, _ = analyse_song(_parts([], groups), 140.0)
    assert song.key == "La mineur" and song.bass_out_of_scale == [] and abs(song.tuning_cents) < 5


@pytest.mark.parametrize("a4", [431.0, 430.0, 428.0])
def test_a_beat_tuned_down_is_read_on_the_nearest_semitone(a4):
    assert tuning(_keys(12.0, a4), FS) == pytest.approx(1200 * math.log2(a4 / 440), abs=3)


def test_a_beat_at_430_hz_keeps_its_key_name():
    groups = [("g1", "808", "bass", _808(12.0, a4=430.0)), ("g2", "Keys", "music", _keys(12.0, 430.0))]
    song, _ = analyse_song(_parts([], groups), 140.0)
    assert song.key == "La mineur" and -45 < song.tuning_cents < -35 and song.bass_out_of_scale == []


def test_the_808_settles_relative_keys_only_with_a_tonic_it_really_plays():
    # Cm Ab Eb Bb: the profiles hesitate between Mi♭ majeur and Do mineur; an 808 on G plays neither
    harmony = _chords_only(MINOR_LOOP)
    key = detect_key(harmony, FS, bass_pitch_classes(np.concatenate([_tone(31, 2.0, 0.5)] * 12), FS))
    assert not key.decided_by_bass and key.display == "Mi♭ majeur (ou Do mineur)"
    # Am Dm Em Am is clearly A minor: an 808 on E and D (no tonic) does not turn it into C major
    chords = _keys(24.0, chords=[[57, 60, 64], [50, 53, 57], [52, 55, 59], [57, 60, 64]])
    bass = bass_pitch_classes(_808(24.0, roots=[28, 26]), FS)
    key = detect_key(chords, FS, bass, fmin=200.0, tuning_cents=0.0)
    assert key.name == "La mineur" and not key.decided_by_bass


@pytest.mark.parametrize("fs", [44100, 96000])
def test_a_very_short_song_is_mixed(fs):
    rng = np.random.default_rng(0)
    n = int(0.3 * fs)
    parts = _parts([("ch0", "Lead", "lead_vocal", rng.normal(0, 0.05, (n, 2)), None)],
                   [("g1", "Instru", "beat", rng.normal(0, 0.1, (n, 2)))], fs=fs)
    assert np.array_equal(mix(parts, 0.0, 140.0, {"ch0": "none"}).premaster, parts.premaster)
    assert np.isfinite(mix(parts, 1.0, 140.0, {"ch0": "none"}).premaster).all()


# -- placement ------------------------------------------------------------------------------

def _sung_only(x: np.ndarray, start_s: float, end_s: float) -> np.ndarray:
    out = np.zeros_like(x)
    out[int(start_s * FS):int(end_s * FS)] = x[int(start_s * FS):int(end_s * FS)]
    return out


def test_doubles_and_backs_pair_up_only_with_a_voice_that_sings_with_them():
    seconds = 15.0
    verse = _sung_only(voice(seconds, seed=21, level=0.12), 0, 5)
    hook = [_sung_only(voice(seconds, seed=s, level=0.12), 10, 15) for s in (22, 23)]
    voices = [("dv", "Double couplet", "double", verse), ("dh1", "Double refrain 1", "double", hook[0]),
              ("dh2", "Double refrain 2", "double", hook[1]),
              ("b1", "Chœur couplet", "back_vocal", _sung_only(voice(seconds, seed=31, level=0.1), 0, 5)),
              ("b2", "Chœur refrain", "back_vocal", _sung_only(voice(seconds, seed=32, level=0.1), 10, 15))]
    placed = {p.key: p for p in stereo.plan_placement(voices, {}, FS, 1.0)}
    assert placed["dv"].position == 0.0 and "aucune autre vraie prise de double" in placed["dv"].reason
    assert placed["dh1"].position == -placed["dh2"].position == pytest.approx(0.85)
    assert "« Double refrain 2 »" in placed["dh1"].reason and "85 % à droite" in placed["dh1"].reason
    assert placed["b1"].position == placed["b2"].position == pytest.approx(0.4)  # never together: no pair
    together = [("b1", "Chœur 1", "back_vocal", voices[3][3]), ("b2", "Chœur 2", "back_vocal", 0.8 * voices[3][3])]
    placed = {p.key: p for p in stereo.plan_placement(together, {}, FS, 0.5)}
    assert placed["b1"].position == -placed["b2"].position == pytest.approx(0.275)


def test_a_third_voice_that_sings_with_a_pair_says_why_it_has_no_partner():
    seconds = 10.0
    voices = [(f"d{i}", f"Double {i}", "double", voice(seconds, seed=40 + i, level=0.1)) for i in range(3)]
    voices += [(f"b{i}", f"Chœur {i}", "back_vocal", voice(seconds, seed=50 + i, level=0.1)) for i in range(3)]
    placed = {p.key: p for p in stereo.plan_placement(voices, {}, FS, 1.0)}
    assert placed["d0"].position == -placed["d1"].position == pytest.approx(0.85)
    assert placed["d2"].position == 0.0 and placed["d2"].reason == (
        "les autres vraies prises de double qui chantent en même temps sont déjà en paire : au centre, sous la "
        "voix principale")
    assert placed["b0"].position == -placed["b1"].position == pytest.approx(0.55)
    assert placed["b2"].position == pytest.approx(0.4) and placed["b2"].reason == (
        "les autres chœurs qui chantent en même temps sont déjà en paire : 40 % à droite, à côté de la voix "
        "principale")


def _fl_reverb(x: np.ndarray, level_db: float) -> np.ndarray:
    """A wide (decorrelated) FL reverb return of the mono voice ``x``, ``level_db`` under it."""
    rng = np.random.default_rng(4)
    t = np.arange(int(1.2 * FS)) / FS
    wet = np.stack([oaconvolve(x, rng.normal(0, 1, t.size) * np.exp(-t / 0.25))[:x.size] for _ in range(2)], 1)
    return wet * 10 ** (level_db / 20) * math.sqrt(np.sum(x ** 2) / np.sum(wet ** 2) * 2)


def _lr_correlation(x: np.ndarray) -> float:
    return float(np.sum(x[:, 0] * x[:, 1]) / math.sqrt(np.sum(x[:, 0] ** 2) * np.sum(x[:, 1] ** 2)))


def test_only_the_voice_is_placed_the_fl_reverb_keeps_its_width():
    dry = voice(12.0, seed=12, notes=[220, 247], level=0.15)
    wet = _fl_reverb(dry[:, 0], -10.0)
    adlib, back = stereo.Placement("a", "Adlib", 0.5, alternate=True), stereo.Placement("b", "Chœur", 0.4)
    # under an ad-lib that changes side, the FL reverb stays as FL made it
    assert np.allclose(stereo.place(dry + wet, FS, adlib, wet) - stereo.place(dry, FS, adlib), wet)
    # with a voice set on one side, it follows it without losing its width
    placed = stereo.place(dry + wet, FS, back, wet) - stereo.place(dry, FS, back)
    assert np.allclose(placed, stereo.balance(wet, 0.4))
    assert _lr_correlation(wet) < 0.5 and _lr_correlation(placed) == pytest.approx(_lr_correlation(wet), abs=1e-9)
    # in the mix: the ad-lib's FL reverb is wide (side −12 dB) but the voice itself is mono: it is placed
    lead = voice(12.0, seed=11)
    parts = _parts([("ch0", "Lead", "lead_vocal", lead, None), ("ch1", "Adlib", "adlib", dry + wet, dry)],
                   [("g1", "Instru", "beat", beat(12.0))])
    assert not stereo.is_mono(dry + wet)
    out = mix(parts, 1.0, 95.0, {"ch0": "none", "ch1": "tracked"})
    adlib = next(p for p in out.parts if p.key == "ch1")
    assert "change de côté (50 % à gauche ou à droite)" in adlib.placement


# -- levels ---------------------------------------------------------------------------------

def _against(x: np.ndarray, instru: np.ndarray, balance_db: float) -> np.ndarray:
    """``x`` set ``balance_db`` against ``instru`` while it sings."""
    return x * 10 ** ((balance_db - balance_against(level_of(x, FS), instru, FS)) / 20)


def test_leads_that_sing_together_are_balanced_as_one():
    instru = beat(16.0)
    takes = [_against(voice(16.0, seed=s), instru, -5.0) for s in (11, 13)]  # stacked: about −2 dB
    parts = _parts([("ch0", "Refrain 1", "vocal", takes[0], None), ("ch1", "Refrain 2", "vocal", takes[1], None)],
                   [("g1", "Instru", "beat", instru)])
    out = mix(parts, 1.0, 95.0, {"ch0": "none", "ch1": "none"})
    res = {p.key: p for p in out.parts}
    assert _gain_db(res["ch0"]) == _gain_db(res["ch1"]) > 0  # one gain: their balance is kept
    reason = next(t.reason for t in res["ch0"].treatments if t.kind == "gain")
    assert "« Refrain 1 » + « Refrain 2 », qui chantent ensemble" in reason
    stack_before = float(re.search(r"chantent ensemble : ([+-]\d+\.\d) dB", reason).group(1))
    assert -4.0 < stack_before < -1.0
    # the stack, not each take, lands on the +1 dB target
    assert stack_before + _gain_db(res["ch0"]) == pytest.approx(1.0, abs=0.06)


def test_a_lead_that_copies_another_is_never_raised():
    instru = beat(16.0)
    lead = _against(voice(16.0, seed=11), instru, -6.0)
    copy = _sung_only(lead, 0.0, 4.0)  # an in-out copy of the first phrase on its own channel
    parts = _parts([("ch0", "Voix", "vocal", lead, None), ("ch1", "Voix (copie)", "vocal", copy, None)],
                   [("g1", "Instru", "beat", instru)])
    out = mix(parts, 1.0, 95.0, {"ch0": "none", "ch1": "none"})
    res = {p.key: p for p in out.parts}
    assert _gain_db(res["ch0"]) > 0
    raised = next(t.reason for t in res["ch0"].treatments if t.kind == "gain")
    assert "réglées d'un même gain sauf « Voix (copie) » (copie, jamais montée) ;" in raised
    kept = next(t for t in res["ch1"].treatments if t.kind == "gain")
    assert kept.label == "Niveau gardé" and "Copie de « Voix »" in kept.reason and res["ch1"].level_change_db == 0


def test_the_level_before_is_the_voice_as_fl_renders_it_with_its_effects():
    lead = voice(12.0, seed=11)
    echo = 0.6 * sum(0.8 ** i * np.roll(lead, int((0.05 + 0.03 * i) * FS), axis=0) for i in range(30))
    parts = _parts([("ch0", "Lead", "lead_vocal", lead + echo, lead)], [("g1", "Instru", "beat", beat(12.0))])
    res = mix(parts, 0.05, 95.0, {"ch0": "tracked"}).parts[0]
    assert res.loudness_before == pytest.approx(integrated_loudness(parts.voices[0].audio, FS), abs=1e-9)
    assert res.loudness_after - res.loudness_before == pytest.approx(res.level_change_db, abs=0.3)


# -- space ----------------------------------------------------------------------------------

def test_no_space_is_added_when_an_fl_reverb_cannot_be_measured():
    lead = voice(12.0, seed=11)
    double = voice(12.0, seed=14, level=0.1)
    parts = _parts([("ch0", "Lead", "lead_vocal", lead, None), ("ch1", "Double", "double", double, None)],
                   [("g1", "Instru", "beat", beat(12.0))])
    out = mix(parts, 1.0, 95.0, {"ch0": "untracked", "ch1": "none"})
    res = {p.key: p for p in out.parts}
    assert math.isnan(out.reverb_lu)
    assert len(res["ch1"].space) == 1 and "Pas d'espace ajouté" in res["ch1"].space[0]
    assert "« Lead »" in res["ch1"].space[0]
    assert not any(t.kind == "dip" for t in res["ch1"].treatments)  # no dip: the stack's sound never flicks


# -- room for the words ---------------------------------------------------------------------

def test_a_beat_that_shares_a_bus_with_the_voices_is_carved_and_shown(monkeypatch):
    seconds = 16.0
    instru = _keys(seconds) + _kicks(seconds)[0] + _hats(seconds) + _snare(seconds)
    riser = 0.02 * np.random.default_rng(1).normal(0, 1, (int(seconds * FS), 2))
    # the 2-track goes through the voices' bus: its stem is skipped, the beat lands in the rest of the mix
    parts = _parts([("ch0", "Lead", "lead_vocal", voice(seconds, seed=11), None)],
                   [("g9", "Riser", "fx", riser)], residual=instru)
    out = mix(parts, 1.0, 140.0, {"ch0": "none"})
    res = {p.key: p for p in out.parts}
    assert [t.kind for t in res["residual"].treatments] == ["carve"] and out.parts[-1].key == "residual"
    assert not res["g9"].treatments  # the riser carries almost nothing of what the dip removes
    monkeypatch.setattr(engine, "MAX_CARVE_DB", 0.0)
    uncarved = mix(parts, 1.0, 140.0, {"ch0": "none"})
    assert "residual" not in {p.key for p in uncarved.parts}
    carved = 10 * math.log10(np.sum((out.premaster - uncarved.premaster) ** 2) / np.sum(instru ** 2))
    assert carved > -35.0  # the beat itself was dipped
    view = viewmodel.mix_view({
        "id": "v", "created_at": "2026-01-01T00:00:00+00:00", "intensity": 1.0, "final_wav": "f.wav",
        "parts": [{"label": p.label, "role": p.role, "treatments": [vars(t) for t in p.treatments],
                   "loudness_before": p.loudness_before, "loudness_after": p.loudness_after,
                   "fl_space": p.fl_space, "space": p.space, "placement": p.placement} for p in out.parts],
        "original": {"loudness_lufs": -10.0, "true_peak_db": -1.0},
        "final": {"loudness_lufs": -9.0, "true_peak_db": -3.0, "sample_rate": FS}, "checks": None})
    assert view["parts"][-1]["role"] == "Reste du mix"
