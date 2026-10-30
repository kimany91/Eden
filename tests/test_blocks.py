"""Building blocks of the mix and master engine: each one checked by measurement."""

import math

import numpy as np
import pytest
from scipy.signal import butter, sosfilt, sosfiltfilt

from eden.mix import dsp, lowend, riding, stereo
from eden.mix.limiter import limit
from eden.mix.loudness import integrated_loudness, true_peak_db
from eden.mix.oversampling import meter_peak
from eden.mix.parts import dry_render_problem, split
from eden.mix.saturation import saturate, soft_clip
from eden.mix.space import (ReverbDesign, design_space, duck, impulse_response, render_space, reverb, tempo_delay,
                            throw_envelope)
from eden.mix.tonality import NOTE_NAMES, bass_pitch_classes, detect_key, tuning
from eden.project.inspector import inspect_project
from eden.project.sources import SearchRoots
from eden.render.pipeline import render_project
from synth_voice import FS, beat, voice
from test_render import make_session, sim_renderer


# -- parts ---------------------------------------------------------------------------------

def test_parts_add_up_to_the_original_mix(tmp_path):
    project = make_session(tmp_path)
    report = inspect_project(project, roots=SearchRoots())
    renders = render_project(project, sim_renderer(), timeout_s=120, report=report)
    parts = split(report, renders)
    assert [v.label for v in parts.voices] == ["Lead", "Adlib"]
    assert {g.label: g.role for g in parts.groups} == {
        "808": "bass", "Instru (joué directement dans le Master)": "beat"}
    total = sum(p.audio.astype(np.float64) for p in parts.all())
    assert np.max(np.abs(total - parts.premaster)) < 1e-12
    assert parts.voices[0].audio.dtype == np.float32 and parts.residual.audio.dtype == np.float64
    # the voices went through the bus reverb: FL also rendered them dry, so the
    # effect part is known exactly and is nothing while the voice is dry
    lead = parts.voices[0]
    assert lead.dry is not None and lead.space is not None
    after_clip = slice(int(4.05 * parts.sample_rate), None)
    assert np.max(np.abs(lead.dry[after_clip])) < 1e-9 < np.max(np.abs(lead.space[after_clip]))


# -- key -------------------------------------------------------------------------------------

def test_a_dry_render_that_does_not_fit_the_voice_is_not_used():
    v = voice(12, seed=5)
    echo = 0.3 * np.roll(v, int(0.25 * FS), axis=0)
    assert dry_render_problem(v + echo, v, FS) is None
    # FL compensated another plugin delay in the copy: the dry voice is late
    assert "décalée" in dry_render_problem(v + echo, np.roll(v, 64, axis=0), FS)
    # the return passed the dry send through once its reverb was bypassed
    assert "la voix elle-même" in dry_render_problem(v + echo, 1.5 * v, FS)
    assert "plus forts que la voix" in dry_render_problem(v + 5 * echo, v, FS)


def _tone(midi, seconds, amp=0.2, a4=440.0):
    f = a4 * 2 ** ((midi - 69) / 12)
    t = np.arange(int(seconds * FS)) / FS
    return amp * sum(np.sin(2 * np.pi * f * h * t) / h for h in range(1, 6))


def _progression(chords, bass, seconds=2.0, reps=3, a4=440.0):
    return np.concatenate([sum(_tone(n, seconds, a4=a4) for n in chord) + _tone(b, seconds, 0.5, a4)
                           for _ in range(reps) for chord, b in zip(chords, bass, strict=True)])


def _chords_only(chords, seconds=2.0, reps=3, a4=440.0):
    return np.concatenate([sum(_tone(n, seconds, a4=a4) for n in chord)
                           for _ in range(reps) for chord in chords])


MINOR_LOOP = [[60, 63, 67], [56, 60, 63], [63, 67, 70], [58, 62, 65]]  # Cm Ab Eb Bb (i VI III VII)


@pytest.mark.parametrize("name,chords,bass,scale_of", [
    ("La mineur", [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]], [33, 29, 36, 31], (9, True)),
    ("Mi majeur", [[52, 56, 59], [59, 63, 66], [61, 64, 68], [57, 61, 64]], [28, 35, 37, 33], (4, False)),
    ("Fa mineur", [[53, 56, 60], [49, 53, 56], [56, 60, 63], [51, 55, 58]], [29, 25, 32, 27], (5, True)),
    ("Sol mineur", [[55, 58, 62], [51, 55, 58], [53, 57, 60], [50, 54, 57]], [31, 27, 29, 26], (7, True)),
])
def test_key_scale_is_found(name, chords, bass, scale_of):
    x = _progression(chords, bass)
    key = detect_key(x, FS, bass_pitch_classes(x, FS))
    tonic, minor = scale_of
    steps = (0, 2, 3, 5, 7, 8, 10) if minor else (0, 2, 4, 5, 7, 9, 11)
    assert key.scale == {(tonic + s) % 12 for s in steps}  # the key or its relative: same notes


def test_the_808_settles_a_minor_loop_against_its_relative_major():
    harmony = _chords_only(MINOR_LOOP)
    bass = np.concatenate([_tone(36, 2.0, 0.5)] * 12)  # the 808 sits on C
    key = detect_key(harmony, FS, bass_pitch_classes(bass, FS))
    assert key.name == "Do mineur" and key.decided_by_bass and not key.relative_close


def test_beat_tuned_to_432_hz_is_measured_and_read_on_its_own_grid():
    x = _chords_only(MINOR_LOOP, a4=432.0)
    cents = tuning(x, FS)
    assert cents == pytest.approx(1200 * math.log2(432 / 440), abs=3)
    assert tuning(_chords_only(MINOR_LOOP), FS) == pytest.approx(0, abs=3)
    key = detect_key(x, FS, bass_pitch_classes(np.concatenate([_tone(36, 2.0, 0.5, 432.0)] * 12), FS, cents))
    assert key.scale == {0, 2, 3, 5, 7, 8, 10} and key.tuning_cents == cents


@pytest.mark.parametrize("midi", [24, 29, 31, 36, 41])
def test_808_root_note(midi):
    root = int(np.argmax(bass_pitch_classes(_tone(midi, 6, 0.5), FS)))  # the strongest pitch class
    assert NOTE_NAMES[root] == NOTE_NAMES[midi % 12]


# -- limiter --------------------------------------------------------------------------------

def test_true_peak_is_also_read_like_a_loudness_meter():
    # a quarter-rate sine with its samples at ±0.707: the peak lies half-way between them, where a
    # 4× meter has an interpolated point; its short filter reads a little above full scale
    t = np.arange(FS) / FS
    x = np.sin(2 * np.pi * FS / 4 * t + math.pi / 4)
    meter = 20 * math.log10(meter_peak(x, FS))
    assert 0.0 < meter < 0.3
    assert true_peak_db(x, FS) == pytest.approx(meter)  # the higher reading is kept


def test_limiter_holds_the_true_peak_ceiling():
    x = (beat(20) + voice(20) * 0.8) * 3.0
    assert true_peak_db(x, FS) > 0
    result = limit(x, FS, ceiling_dbtp=-1.0)
    assert result.true_peak_db <= -1.0 + 0.02
    assert result.max_reduction_db < 0


def test_limiter_is_transparent_under_the_ceiling():
    x = beat(5) * 0.1
    result = limit(x, FS, ceiling_dbtp=-1.0)
    assert np.array_equal(result.audio, x) and result.max_reduction_db == 0.0


# -- reverb and delay ---------------------------------------------------------------------

def _rt60(sig, lo, hi):
    band = sosfiltfilt(butter(3, [lo, hi], btype="bandpass", fs=FS, output="sos"), sig)
    energy = np.cumsum(band[::-1] ** 2)[::-1]
    edc = 10 * np.log10(energy / energy[0] + 1e-30)
    return (np.argmax(edc < -35) - np.argmax(edc < -5)) / FS * 2


def test_reverb_decay_per_band_and_predelay():
    d = ReverbDesign(decay_s=1.2, predelay_ms=30, hf_ratio=0.5, lf_ratio=0.8)
    ir = impulse_response(d, FS)
    assert _rt60(ir[:, 0], 707, 1414) == pytest.approx(1.2, rel=0.15)
    assert _rt60(ir[:, 0], 5657, 11314) == pytest.approx(0.6, rel=0.15)
    assert _rt60(ir[:, 0], 88, 177) == pytest.approx(0.96, rel=0.15)
    assert not ir[: int(0.029 * FS)].any()
    assert abs(np.corrcoef(ir[:, 0], ir[:, 1])[0, 1]) < 0.1  # wide, decorrelated tail


def test_tempo_delay_lands_on_the_grid():
    click = np.zeros(FS * 3)
    click[0] = 1.0
    echoes = tempo_delay(click, FS, 60 / 120, feedback=0.5, repeats=3, ping_pong=True)
    # a quarter note at 120 BPM = 0.5 s: first echo on the left, the next one on the right
    assert abs(np.argmax(np.abs(echoes[:, 0])) - FS // 2) < 0.002 * FS
    assert abs(np.argmax(np.abs(echoes[:, 1])) - FS) < 0.002 * FS
    assert np.max(np.abs(echoes[: FS // 2 - 200])) == 0


def test_effect_returns_duck_under_the_voice():
    v = voice(10)
    wet = reverb(v, FS, ReverbDesign(1.0, 20))
    ducked = duck(wet, v, FS, depth_db=6, release_ms=200)
    assert 10 * math.log10(np.sum(ducked ** 2) / np.sum(wet ** 2)) < -3


# -- stereo ---------------------------------------------------------------------------------

def _low_side_ratio_db(x):
    """Side energy relative to mid energy below 120 Hz."""
    lp, _ = stereo.linkwitz_riley(FS, 120.0)
    mid, side = stereo.mid_side(x)
    return stereo._db(float(np.sum(sosfilt(lp, side) ** 2)), float(np.sum(sosfilt(lp, mid) ** 2)))


def test_mono_low_end_keeps_the_top_wide():
    rng = np.random.default_rng(0)
    t = np.arange(FS * 3) / FS
    x = np.stack([np.sin(2 * np.pi * 50 * t), np.sin(2 * np.pi * 50 * t + 1.2)], 1) * 0.3
    x = x + rng.normal(0, 0.05, x.shape)
    assert _low_side_ratio_db(stereo.mono_below(x, FS, 120)) < _low_side_ratio_db(x) - 20


def test_pan_is_constant_power_and_mid_side_gives_the_signal_back():
    mono = np.ones(100)
    energies = [float(np.sum(stereo.pan(mono, p) ** 2)) for p in (-1, -0.3, 0, 0.6, 1)]
    assert max(energies) - min(energies) < 1e-9
    x = np.stack([np.ones(10), np.zeros(10)], 1)
    mid, side = stereo.mid_side(x)
    assert np.array_equal(stereo.from_mid_side(mid, side), x)
    narrowed = stereo.from_mid_side(mid, side * 0.0)  # without its side, the signal is mono
    assert np.array_equal(narrowed[:, 0], narrowed[:, 1])


# -- saturation -------------------------------------------------------------------------

def test_saturation_adds_harmonics_without_aliasing():
    t = np.arange(FS) / FS
    x = 0.8 * np.sin(2 * np.pi * 5000 * t)
    spectrum = np.abs(np.fft.rfft(saturate(x, FS, drive=3.0) * np.hanning(FS)))
    freqs = np.fft.rfftfreq(FS, 1 / FS)

    def level(f):
        return spectrum[(freqs > f - 10) & (freqs < f + 10)].max()

    assert 20 * math.log10(level(15000) / level(5000)) > -30  # 3rd harmonic present
    assert 20 * math.log10(level(9100) / level(5000)) < -90  # folded 7th harmonic absent
    assert np.array_equal(saturate(x, FS, drive=3.0, mix=0.0), x)


def test_soft_clip_rounds_peaks():
    t = np.arange(FS) / FS
    x = np.stack([1.4 * np.sin(2 * np.pi * 200 * t)] * 2, 1)
    assert np.max(np.abs(soft_clip(x, FS, 0.9))) < 0.93
    assert integrated_loudness(soft_clip(x, FS, 0.9), FS) < integrated_loudness(x, FS)


# -- 808 and kick ---------------------------------------------------------------------------

def _808(midis, note_s=1.5, gap_s=0.5, a4=440.0):
    out = []
    for midi in midis:
        f = a4 * 2 ** ((midi - 69) / 12)
        t = np.arange(int(note_s * FS)) / FS
        out += [np.sin(2 * np.pi * f * t) * np.exp(-t / 1.0), np.zeros(int(gap_s * FS))]
    sig = 0.5 * np.concatenate(out)
    return np.stack([sig, sig], axis=1)


def test_808_notes_are_tracked_on_the_beat_grid():
    notes = lowend.track_bass(_808([33, 36, 40, 31]), FS)
    assert [n.pitch_class for n in notes] == [9, 0, 4, 7]  # A1 C2 E2 G1
    assert all(abs(n.cents_off) < 15 for n in notes)
    report = lowend.analyse(_808([33, 36, 40, 31], a4=432.0), None, _808([33]), FS, None, -31.8)
    assert report.detune_cents < 15  # a 432 Hz 808 in a 432 Hz beat is in tune


def test_808_out_of_scale_and_root():
    report = lowend.analyse(_808([33, 33, 33, 34]), None, _808([33]), FS, {9, 11, 0, 2, 4, 5, 7})
    assert report.root_name == "La" and report.out_of_scale == ["Si♭"]


def test_808_glides_are_not_read_as_notes():
    # F1 sliding down to C1 in C minor: the pitches it passes through are not notes it plays
    bars = []
    for _ in range(16):
        f = np.concatenate([np.full(int(0.3 * FS), 43.65), np.geomspace(43.65, 32.70, int(0.2 * FS)),
                            np.full(int(0.5 * FS), 32.70)])
        t = np.arange(f.size) / FS
        bars += [0.5 * np.exp(-t / 2.0) * np.sin(2 * np.pi * np.cumsum(f) / FS), np.zeros(int(0.1 * FS))]
    x = np.stack([np.concatenate(bars)] * 2, axis=1)
    report = lowend.analyse(x, None, x, FS, {0, 2, 3, 5, 7, 8, 10})
    assert report.out_of_scale == [] and report.root_name == "Do"


def test_trap_kicks_are_all_found():
    """140 BPM pattern with a ghost kick at −9 dB, kicks on the previous kick's tail and snares."""
    rng = np.random.default_rng(3)
    step = 60 / 140 / 4
    pattern = {0: 1.0, 3: 0.35, 7: 1.0, 10: 0.9, 11: 0.9, 14: 0.5}
    n = int((64 * step + 1) * FS)
    drums, kicks = np.zeros(n), []
    t = np.arange(int(0.35 * FS)) / FS
    click = sosfilt(butter(2, 3000, "highpass", fs=FS, output="sos"), rng.normal(0, 1, t.size)) * np.exp(-t / 0.003)
    body = np.exp(-t / 0.12) * np.sin(2 * np.pi * np.cumsum(50 + 100 * np.exp(-t / 0.02)) / FS) + 0.3 * click
    ts = np.arange(int(0.2 * FS)) / FS
    snare = 0.7 * (0.6 * np.sin(2 * np.pi * 190 * ts) * np.exp(-ts / 0.04) + rng.normal(0, 0.5, ts.size) * np.exp(-ts / 0.06))
    for i in range(64):
        start = int((0.5 + i * step) * FS)
        if i % 16 in pattern:
            drums[start:start + body.size] += pattern[i % 16] * body
            kicks.append(start / FS)
        if i % 16 in (4, 12):
            drums[start:start + snare.size] += snare
    found = lowend._onsets(np.stack([drums, drums], 1) * 0.4, FS) / 1000
    kicks = np.array(kicks)
    assert all(np.min(np.abs(found - k)) <= 0.03 for k in kicks)
    assert all(np.min(np.abs(kicks - f)) <= 0.03 for f in found)


def test_kick_collisions_are_measured_and_ducked_only_below_the_crossover():
    bass = np.tanh(3 * _808([31] * 4, note_s=2.0, gap_s=0.0)) / 3  # a distorted 808: it has harmonics
    drums = beat(8, level=0.6)
    overlap, existing, hits = lowend.kick_808_interaction(bass, drums, FS)
    assert overlap > 0.8 and existing < 2.0 and hits.size >= 12
    ducked = lowend.duck_low_band(bass, FS, hits, 3.0)
    _, after, _ = lowend.kick_808_interaction(ducked, drums, FS)
    assert after == pytest.approx(existing + 3.0, abs=1.0)
    high_before, _ = dsp.split_band(bass, FS, 300.0, None)
    high_after, _ = dsp.split_band(ducked, FS, 300.0, None)
    assert abs(10 * math.log10(np.sum(high_after ** 2) / np.sum(high_before ** 2))) < 0.3  # harmonics kept
    assert lowend.duck_low_band(bass, FS, hits, 0.0) is bass


def test_harmonics_make_a_bare_808_audible_on_small_speakers():
    bass = _808([31, 33])
    notes = lowend.track_bass(bass, FS)
    before = lowend.harmonics_db(bass, FS, notes)
    after = lowend.harmonics_db(lowend.add_harmonics(bass, FS), FS, notes)
    assert before < -40 and -25 < after < -8
    assert lowend.add_harmonics(bass, FS, k=0.0) is bass
    # not only the octave: the 3rd to 5th harmonics, from which the ear rebuilds the note
    f0 = 440 * 2 ** ((31 - 69) / 12)
    t = np.arange(4 * FS) / FS
    sine = np.stack([0.5 * np.sin(2 * np.pi * f0 * t)] * 2, 1)
    added = lowend.add_harmonics(sine, FS)[:, 0] - sine[:, 0]
    spectrum = np.abs(np.fft.rfft(added * np.hanning(added.size)))
    freqs = np.fft.rfftfreq(added.size, 1 / FS)

    def level(h):
        return 20 * math.log10(spectrum[(freqs > h * f0 - 2) & (freqs < h * f0 + 2)].max())

    assert level(3) > level(2) - 6 and level(5) > level(2) - 12


# -- riding ---------------------------------------------------------------------------------

def _differences(voice, beat):
    """(phrases, voice minus beat above ``riding.MASKING_FROM_HZ`` in dB per phrase) at 95 BPM."""
    phrases, voice_db, beat_db, _ = riding.phrase_levels(voice, beat, FS, 95.0)
    return phrases, riding._differences(voice_db, beat_db)


def _steadiness_db(voice, beat):
    """Spread (P90 − P10) of the phrase-by-phrase voice-minus-beat difference."""
    d = _differences(voice, beat)[1]
    d = d[np.isfinite(d)]
    return float(np.percentile(d, 90) - np.percentile(d, 10)) if d.size >= 2 else 0.0


def test_riding_steadies_the_voice_above_the_beat_phrase_by_phrase():
    v, b = voice(30, seed=7, phrase_spread_db=8), beat(30)
    before = _steadiness_db(v, b)
    r = riding.ride(v, b, FS, 95.0, 1.0)
    assert len(r.phrases) == 6 and r.moved >= 1 and r.max_change_db <= riding.MAX_RIDE_DB
    assert sum(p.gain_db > 0 for p in r.phrases) and sum(p.gain_db < 0 for p in r.phrases)  # around the median
    assert _steadiness_db(riding.apply_ride(v, r), b) < before - 2.0
    steps = np.abs(np.diff(20 * np.log10(r.gain[:: FS // 1000])))
    assert steps.max() < 0.2  # no jump: fades only
    # through the rest after a phrase the gain stays the phrase's own (its FL echoes keep their level)
    first = r.phrases[1]
    rest = int((first.end_s + 0.3) * FS)
    assert 20 * math.log10(r.gain[rest]) == pytest.approx(first.gain_db, abs=0.05)
    assert np.all(riding.ride(v, b, FS, 95.0, 0.0).gain == 1)


def test_riding_sees_rap_phrases_separated_by_short_rests():
    # 1.6 s phrases separated by 0.35 s rests (a little more than an eighth at 95 BPM)
    sig = np.concatenate([np.concatenate([voice(1.6, seed=s)[:, 0] * (0.5 if s % 2 else 1.0), np.zeros(int(0.35 * FS))])
                          for s in range(8)])
    v = np.stack([sig, sig], 1)
    phrases, diffs = _differences(v, beat(v.shape[0] / FS))
    assert len(phrases) == 8 and np.ptp(diffs) > 4


@pytest.mark.parametrize("bpm,felt", [(140, 70), (95, 95), (160, 80), (60, 120)])
def test_felt_pulse(bpm, felt):
    assert riding.felt_quarter(bpm) == pytest.approx(60 / felt)


# -- placement ------------------------------------------------------------------------------

def test_adlib_phrases_alternate_sides_without_losing_power():
    v = voice(16, seed=9)
    y = stereo.alternate_pan(v, FS, 0.5)
    sides = []
    for start, end in ((0, 4), (5, 9), (10, 14)):
        seg = y[int(start * FS):int(end * FS)]
        sides.append(10 * math.log10(np.sum(seg[:, 0] ** 2) / np.sum(seg[:, 1] ** 2)))
    assert sides[0] * sides[1] < 0 and sides[1] * sides[2] < 0 and min(map(abs, sides)) > 5
    assert np.sum(y ** 2) == pytest.approx(np.sum(v ** 2), rel=1e-6)


def test_a_double_that_copies_the_lead_stays_centred():
    lead = voice(12, seed=1)
    copy = np.roll(lead, 300, axis=0) * 0.7
    take = voice(12, seed=5)
    doubles = [("c", "Copie", "double", copy), ("t1", "Prise 1", "double", take),
               ("t2", "Prise 2", "double", voice(12, seed=6))]
    copies = {key: stereo.copy_correlation(audio, lead, FS) for key, _, _, audio in doubles}
    placements = stereo.plan_placement(doubles, copies, FS, 1.0)
    by_key = {p.key: p for p in placements}
    assert by_key["c"].position == 0.0 and "peigne" in by_key["c"].reason
    assert by_key["t1"].position == -by_key["t2"].position != 0.0


# -- space plan ----------------------------------------------------------------------------

def test_space_plan_follows_the_felt_tempo():
    plan = design_space(140.0, "lead_vocal", 1.0)
    sends = {s.name: s for s in plan.sends}
    assert set(sends) == {"ambience", "plate", "delay", "throw"}
    assert sends["delay"].delay_s == pytest.approx(60 / 70 / 2)  # an eighth of the felt pulse
    assert sends["throw"].delay_s == pytest.approx(60 / 70)
    assert 0.8 <= sends["plate"].reverb.decay_s <= 1.4 and 20 <= sends["plate"].reverb.predelay_ms <= 80
    assert "throw" not in {s.name for s in design_space(140.0, "adlib", 1.0).sends}
    assert design_space(140.0, "lead_vocal", 0.0).sends == []


def test_throws_only_feed_phrase_endings():
    v = voice(15, seed=2)
    env = throw_envelope(v, FS, 0.5)
    assert 0.0 < env.mean() < 0.15
    # each phrase lasts 4 s then 1 s of silence: the throw sits on the last 300 ms of a phrase
    assert env[int(3.8 * FS)] > 0.9 and env[int(2.0 * FS)] < 0.01


def test_space_returns_sit_under_the_voice_and_duck():
    v = voice(15, seed=2)
    wet, report = render_space(v, FS, design_space(95.0, "lead_vocal", 1.0), 1.0)
    assert len(report) == 4
    share = integrated_loudness(wet, FS) - integrated_loudness(v, FS)
    assert -20 < share < -8
    # in the pauses the returns are louder relative to the voice than while it sings
    gap = slice(int(4.1 * FS), int(4.9 * FS))
    sung = slice(int(1 * FS), int(3.5 * FS))
    assert np.std(wet[gap]) > 0.3 * np.std(wet[sung])
