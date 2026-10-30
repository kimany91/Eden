"""Eden's mixing engine: measurements, processors, rules, full chain, mastering and export."""

import math
import os
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from scipy.signal import sosfreqz

from eden.mix import dsp, stereo
from eden.mix.analysis import measure_vocal
from eden.mix.engine import LEAD_BALANCE, MAX_LEAD_CHANGE_DB, _level_change, mix
from eden.mix.export import ExportError, export_wav
from eden.mix.loudness import integrated_loudness, k_weighting, loudness_range, true_peak_db
from eden.mix.master import CEILING_DBTP, DENSE_CEILING_DBTP, TARGET_LUFS, master
from eden.mix.parts import Part, Parts, split
from eden.mix.session import MixError, list_versions, mix_project
from eden.mix.treatments import Treatment, apply
from eden.mix.vocal import plan_voice
from eden.project.inspector import inspect_project
from eden.project.sources import SearchRoots
from eden.render.pipeline import render_project
from synth_voice import FS, beat, voice
from test_render import make_session, sim_renderer


def sine(f, seconds=10.0, fs=48000, amp=1.0, phase=0.0):
    return amp * np.sin(2 * np.pi * f * np.arange(int(seconds * fs)) / fs + phase)


# -- loudness (ITU-R BS.1770 / EBU R128) -----------------------------------------

def test_k_weighting_matches_the_standard_at_48k():
    expected = np.array([
        [1.53512485958697, -2.69169618940638, 1.19839281085285, 1, -1.69065929318241, 0.73248077421585],
        [1.0, -2.0, 1.0, 1, -1.99004745483398, 0.99007225036621],
    ])
    assert np.allclose(k_weighting(48000), expected, atol=1e-9)


@pytest.mark.parametrize("fs", [44100, 48000, 96000])
def test_reference_sine_loudness(fs):
    s = sine(997, fs=fs)
    assert integrated_loudness(s, fs) == pytest.approx(-3.01, abs=0.02)
    assert integrated_loudness(np.stack([s, s], 1), fs) == pytest.approx(0.0, abs=0.02)
    assert integrated_loudness(np.stack([s, s], 1) * 0.1, fs) == pytest.approx(-20.0, abs=0.02)


def test_gating_ignores_silence():
    s = sine(997, seconds=5)
    with_silence = np.concatenate([s, np.zeros(48000 * 20)])
    # blocks straddling the end of the tone pass the relative gate, as the standard says
    assert integrated_loudness(with_silence, 48000) == pytest.approx(-3.01, abs=0.2)
    assert integrated_loudness(np.zeros(48000 * 3), 48000) == -math.inf


def test_true_peak_sees_between_samples():
    x = sine(12000, seconds=1, phase=math.pi / 4)  # samples at ±0.707 of a full-scale wave
    assert true_peak_db(x, 48000) == pytest.approx(0.0, abs=0.2)
    assert 20 * math.log10(np.max(np.abs(x))) == pytest.approx(-3.01, abs=0.01)


def test_loudness_range_of_a_two_level_signal():
    quiet, loud = sine(997, 20, amp=0.1), sine(997, 20, amp=1.0)
    assert loudness_range(np.concatenate([quiet, loud]), 48000) == pytest.approx(20.0, abs=1.0)
    assert loudness_range(loud, 48000) < 0.5


# -- processors ------------------------------------------------------------------------

def _gain_db(sos, f, fs=44100):
    _, h = sosfreqz(sos, worN=[f], fs=fs)
    return 20 * math.log10(abs(h[0]))


def test_filters():
    assert _gain_db(dsp.highpass_sos(44100, 80), 30) < -15
    assert _gain_db(dsp.highpass_sos(44100, 80), 1000) == pytest.approx(0, abs=0.1)
    assert _gain_db(dsp.peaking_sos(44100, 2500, 6, -3), 2500) == pytest.approx(-3, abs=0.05)
    assert _gain_db(dsp.peaking_sos(44100, 2500, 6, -3), 1000) == pytest.approx(0, abs=0.2)
    assert _gain_db(dsp.shelf_sos(44100, 10000, 2.0), 20000) == pytest.approx(2, abs=0.1)
    assert _gain_db(dsp.shelf_sos(44100, 10000, 2.0), 500) == pytest.approx(0, abs=0.1)
    assert _gain_db(dsp.shelf_sos(44100, 100, -3.0, high=False), 20) == pytest.approx(-3, abs=0.1)


def test_band_split_is_exact():
    x = np.random.default_rng(0).normal(0, 0.1, (FS * 2, 2))
    for lo, hi in ((1500, 4000), (4500, None), (None, 200)):
        band, rest = dsp.split_band(x, FS, lo, hi)
        assert np.max(np.abs(band + rest - x)) < 1e-12


def test_processors_at_zero_change_nothing():
    x = voice(seconds=6)
    assert not dsp.compressor_gain_db(x, FS, -20, 1.0)[0].any()
    assert not dsp.deess_gain_db(x, FS, -30, 0.0)[2].any()
    assert dsp.parallel_compress(x, FS, -30, 0.0) is x
    env, size = dsp.activity_envelope(x, FS, -40)
    assert dsp.dip_band_when(x, FS, env, size, 0.0) is x


def test_compressor_reduces_loud_parts_only():
    quiet, loud = sine(1000, 2, FS, 0.05), sine(1000, 2, FS, 0.5)
    x = np.concatenate([quiet, loud])
    gr, size = dsp.compressor_gain_db(x, FS, threshold_db=-20, ratio=4, knee_db=0)
    y = dsp._apply_gain(x, dsp._to_samples(gr, size, x.shape[0]))
    q = slice(FS // 2, FS + FS // 2)
    lo = slice(2 * FS + FS // 2, 3 * FS + FS // 2)
    assert np.max(np.abs(y[q])) == pytest.approx(0.05, rel=0.01)  # under threshold: untouched
    # 0.5 peak = −9 dB RMS-ish: 11 dB over threshold → about 8 dB of reduction at 4:1
    assert 20 * math.log10(np.max(np.abs(y[lo])) / 0.5) == pytest.approx(-8.3, abs=1.0)


def test_compressor_cap_and_tail_hold():
    x = voice(seconds=8, seed=2)
    gr, _ = dsp.compressor_gain_db(x, FS, -40.0, 4.0, max_reduction_db=3.0)
    assert gr.min() >= -3.0 - 1e-6
    hold = np.zeros(gr.size, dtype=bool)
    hold[2000:4000] = True
    held, _ = dsp.compressor_gain_db(x, FS, -40.0, 4.0, hold=hold)
    assert np.ptp(held[2000:4000]) == 0.0  # frozen exactly while the mask is on: the look-ahead does not move it


def test_tail_hold_freezes_at_the_phrase_mean():
    # frozen at the phrase's last value (near 0 dB) a tail would come up by the phrase's reduction;
    # the mean is weighted by power, like the loudness the make-up gives back
    g = np.concatenate([np.full(500, -4.0), np.zeros(200), np.full(300, -2.0)])
    hold = np.zeros(g.size, dtype=bool)
    hold[500:700] = True
    out = dsp._smooth(g, 1.0, 50.0, hold=hold, power=np.ones(g.size))
    free = dsp._smooth(g[:500], 1.0, 50.0)
    assert out[600] == pytest.approx(10 * np.log10(np.mean(10 ** (free / 10))))


def test_program_dependent_release_is_slower_after_long_reduction():
    short = np.concatenate([np.zeros(300), np.full(100, -6.0), np.zeros(2000)])
    long = np.concatenate([np.zeros(300), np.full(1500, -6.0), np.zeros(2000)])
    a = dsp._smooth(short, 1.0, 50.0, slow_release_frames=800.0, slow_after_frames=200.0)
    b = dsp._smooth(long, 1.0, 50.0, slow_release_frames=800.0, slow_after_frames=200.0)
    assert a[400 + 200] > -0.2  # recovered within 200 ms
    assert b[1800 + 200] < -3.0  # still half-way down 200 ms after a long reduction


def test_deesser_only_touches_the_high_band():
    x = voice(sibilance=1.5, seconds=8)
    high, rest, gr, size = dsp.deess_gain_db(x, FS, threshold_db=-40, max_reduction_db=8)
    change = rest + dsp._apply_gain(high, dsp._to_samples(gr, size, x.shape[0])) - x
    low_change, _ = dsp.split_band(change, FS, None, 2000)
    assert np.sum(change ** 2) > 1e-3
    assert np.sum(low_change ** 2) < 0.01 * np.sum(change ** 2)


# -- rules on voices with known defects ---------------------------------------------

def _kinds(treatments):
    return [t.kind for t in treatments]


def test_a_clean_voice_gets_only_the_shaping_steps():
    v = voice(seed=3, notes=[131, 147])
    treatments = plan_voice(measure_vocal(v, FS), "lead_vocal", 1.0, False)
    assert not {"highpass", "eq", "deesser", "parallel"} & set(_kinds(treatments))
    out = apply(v, FS, treatments)
    # the make-up gain gives back what the compression took: the voice keeps its loudness
    assert _kinds(treatments)[-1] == "makeup"
    assert integrated_loudness(out, FS) == pytest.approx(integrated_loudness(v, FS), abs=0.05)


def test_a_stage_with_nothing_to_do_is_not_applied():
    v = voice(seed=3)
    idle = Treatment("compressor", "Compression", "test", {"threshold_db": 0.0, "ratio": 4.0, "attack_ms": 5.0,
                                                           "release_ms": 100.0})
    out = apply(v, FS, [idle])
    assert not idle.applied and np.array_equal(out, v)


@pytest.mark.parametrize("kwargs,kind,check", [
    ({"resonance_hz": 2500, "seed": 4}, "eq", lambda t: abs(t.params["freq_hz"] - 2500) < 150),
    ({"rumble": 0.08, "seed": 5}, "highpass", lambda t: 60 <= t.params["freq_hz"] <= 80),
    ({"sibilance": 1.2, "seed": 6}, "deesser", lambda t: t.params["max_reduction_db"] > 0),
    ({"phrase_spread_db": 16, "seed": 7}, "compressor", lambda t: t.params["ratio"] > 1.5),
])
def test_each_defect_gets_its_treatment(kwargs, kind, check):
    treatments = plan_voice(measure_vocal(voice(**kwargs), FS), "lead_vocal", 1.0, False)
    matching = [t for t in treatments if t.kind == kind]
    assert matching and check(matching[0]) and matching[0].reason


def test_chain_follows_the_engineers_order():
    kinds = _kinds(plan_voice(measure_vocal(voice(sibilance=1.2, rumble=0.08, phrase_spread_db=12, seed=8), FS),
                              "lead_vocal", 1.0, False))
    # breaths before anything raises them, clean-up, light de-essing before the compressors pump on
    # the s, compression, colour, the main de-esser on what the colour brightened, then the level the
    # chain took is given back
    assert kinds == ["breath", "highpass", "deesser", "compressor", "compressor", "parallel", "saturation",
                     "deesser", "makeup"]


def test_treatments_fix_what_they_target():
    sib = voice(sibilance=1.2, seed=6)
    m = measure_vocal(sib, FS)
    after = measure_vocal(apply(sib, FS, plan_voice(m, "lead_vocal", 1.0, False)), FS)
    assert after.sibilant_excess_db < m.sibilant_excess_db - 3

    dyn = voice(phrase_spread_db=16, seed=7)
    m = measure_vocal(dyn, FS)
    after = measure_vocal(apply(dyn, FS, plan_voice(m, "lead_vocal", 1.0, False)), FS)
    assert after.dynamic_spread_db < m.dynamic_spread_db - 3


def test_tail_safe_chain_limits_reduction_and_adds_no_parallel_path():
    m = measure_vocal(voice(phrase_spread_db=16, seed=7), FS)
    safe = plan_voice(m, "lead_vocal", 1.0, True)
    assert "parallel" not in _kinds(safe)
    comps = [t for t in safe if t.kind == "compressor"]
    assert comps and all(t.params["max_reduction_db"] <= 3.0 and t.params["tail_safe"] for t in comps)


def test_intensity_scales_the_treatments():
    m = measure_vocal(voice(sibilance=1.2, seed=6), FS)
    full = [t for t in plan_voice(m, "lead_vocal", 1.0, False) if t.kind == "deesser"][-1].params["max_reduction_db"]
    half = [t for t in plan_voice(m, "lead_vocal", 0.5, False) if t.kind == "deesser"][-1].params["max_reduction_db"]
    assert half == pytest.approx(full / 2)
    assert plan_voice(m, "lead_vocal", 0.0, False) == []


# -- the whole mix on synthetic parts ----------------------------------------------------

def _parts(lead_level=0.25, adlib_level=0.6, with_dry=False):
    # phrases up to ±8 dB apart: after the leveling and peak compressors riding still has work
    lead = voice(seed=11, phrase_spread_db=16) * lead_level
    adlib, instru = voice(seed=12, notes=[220, 247]) * adlib_level, beat()
    space = 0.3 * np.roll(lead, int(0.25 * FS), axis=0) if with_dry else None
    lead_full = lead + space if with_dry else lead
    voices = [Part("ch0", "Lead", "lead_vocal", lead_full, [0], dry=lead if with_dry else None),
              Part("ch1", "Adlib", "adlib", adlib, [1])]
    groups = [Part("beat", "Instru", "beat", instru, [2])]
    premaster = lead_full + adlib + instru
    residual = premaster - lead_full - adlib - instru
    return Parts(voices, groups, Part("residual", "Reste", "residual", residual), FS, premaster)


def test_lead_balance_window():
    target, low, high = LEAD_BALANCE
    cap = MAX_LEAD_CHANGE_DB
    assert low <= 0.0 <= high and _level_change(0.0, LEAD_BALANCE, 1.0, cap) == 0.0  # experts' usual balance
    assert _level_change(low - 1.0, LEAD_BALANCE, 1.0, cap) == pytest.approx(target - low + 1.0)
    assert _level_change(14.0, LEAD_BALANCE, 1.0, cap) == -10.0  # a lead: never more than 10 dB at once


def test_mix_at_zero_is_exactly_the_original():
    parts = _parts()
    out = mix(parts, 0.0, 95.0, {"ch0": "none", "ch1": "none"})
    assert np.array_equal(out.premaster, parts.premaster)
    assert all(not p.treatments for p in out.parts) and out.staging_gain_db == 0.0


def test_mix_balances_voices_rides_the_lead_and_makes_room():
    parts = _parts()
    out = mix(parts, 1.0, 95.0, {"ch0": "none", "ch1": "none"})
    res = {p.key: p for p in out.parts}
    lead_gain = [t for t in res["ch0"].treatments if t.kind == "gain"]
    assert lead_gain and lead_gain[0].params["gain_db"] > 0  # buried lead brought up
    assert res["ch0"].ride.get("moved", 0) >= 1
    adlib_gain = [t for t in res["ch1"].treatments if t.kind == "gain"]
    assert adlib_gain and adlib_gain[0].params["gain_db"] == pytest.approx(-4.0)  # 4 dB limit
    assert res["ch1"].placement and "change de côté" in res["ch1"].placement
    assert any(t.kind == "dip" for t in res["ch1"].treatments)
    assert [t.kind for t in res["beat"].treatments] == ["carve"]
    assert res["ch0"].space and res["ch1"].space  # both voices got Eden's sends
    assert out.reverb_lu <= -16.0 + 0.1
    assert integrated_loudness(out.premaster, FS) == pytest.approx(integrated_loudness(parts.premaster, FS), abs=0.05)
    assert out.song.tempo_bpm == 95.0 and out.song.key
    assert all(t.applied for p in out.parts for t in p.treatments)  # only what changed something is reported


def test_fl_effects_are_kept_and_no_space_is_added_on_top():
    parts = _parts(with_dry=True)
    lead = parts.voices[0]
    alone = Parts([lead], [], Part("residual", "Reste", "residual", np.zeros_like(lead.audio)), FS, lead.audio)
    out = mix(alone, 1.0, 95.0, {"ch0": "tracked"})
    res = out.parts[0]
    assert res.fl_space == "tracked" and not res.space
    # in the pause after the first phrase only the FL echo sounds: it is still there, at the voice's new level
    gap = slice(int(4.02 * FS), int(4.2 * FS))
    kept = np.sum(out.premaster[gap] ** 2) / np.sum(lead.space[gap] ** 2)
    expected = 10 ** ((res.level_change_db + out.staging_gain_db) / 10)
    assert kept == pytest.approx(expected, rel=0.5)


def test_the_users_fl_reverb_counts_in_the_reverb_ceiling():
    lead = voice(seed=11) * 0.25
    tail = sum(0.6 * 0.8 ** i * np.roll(lead, int((0.05 + 0.03 * i) * FS), axis=0) for i in range(30))
    wet_lead = lead + tail  # a very wet FL reverb on the lead
    adlib, instru = voice(seed=12, notes=[220, 247]) * 0.15, beat()
    parts = Parts([Part("ch0", "Lead", "lead_vocal", wet_lead, [0], dry=lead), Part("ch1", "Adlib", "adlib", adlib, [1])],
                  [Part("beat", "Instru", "beat", instru, [2])],
                  Part("residual", "Reste", "residual", np.zeros_like(instru)), FS, wet_lead + adlib + instru)
    out = mix(parts, 1.0, 95.0, {"ch0": "tracked", "ch1": "none"})
    adlib_notes = next(p for p in out.parts if p.key == "ch1").space
    [note] = adlib_notes  # Eden's own reverb made way: its sends, out of the mix, are no longer listed
    assert note.startswith("Effets d'Eden retirés : avec tes seuls effets FL, la reverb de tout le morceau")
    assert out.reverb_lu > -16.0 - 0.1  # the user's reverb alone is above the ceiling: kept as is


def test_untracked_fl_space_means_tail_safe_compression():
    parts = _parts()
    out = mix(parts, 1.0, 95.0, {"ch0": "untracked", "ch1": "none"})
    res = {p.key: p for p in out.parts}
    comps = [t for t in res["ch0"].treatments if t.kind == "compressor"]
    assert comps and all(t.params["tail_safe"] for t in comps) and not res["ch0"].space


# -- mastering ----------------------------------------------------------------------------

def test_master_reaches_the_target_under_the_ceiling():
    t = np.arange(int(24 * FS)) / FS
    sub = 0.35 * np.sin(2 * np.pi * 48 * t) * (np.sin(2 * np.pi * 0.25 * t) > 0)
    x = voice(seed=11, level=0.3) + beat(level=0.4) + np.stack([sub, sub], axis=1)
    r = master(x, FS, 1.0, tempo_bpm=140)
    lufs = r.checks.integrated_lufs
    # on target, or a little under it and said so (peak-reduction budget reached)
    assert abs(lufs - TARGET_LUFS) <= 0.5 or (TARGET_LUFS - 1.5 < lufs < TARGET_LUFS and r.warnings)
    ceiling = r.treatments[-1].measured["ceiling_dbtp"]
    assert ceiling in (CEILING_DBTP, DENSE_CEILING_DBTP)
    assert r.checks.true_peak_dbtp <= ceiling + 0.05
    assert r.checks.plr_db > 6.0
    assert [t.kind for t in r.treatments][-1] == "loudness"
    spotify = next(p for p in r.checks.platforms if p.name == "Spotify")
    assert spotify.heard_lufs == pytest.approx(-14.0, abs=0.01) and spotify.gain_db < 0
    assert master(x, FS, 0.0).audio is x


def test_ceiling_follows_how_dense_the_target_makes_the_master():
    x = beat(16, level=0.5) * 3.0
    loud = master(x, FS, 1.0, tempo_bpm=140)  # −9 LUFS: at most 7 dB between peak and loudness at −2 dBTP
    assert loud.treatments[-1].measured["ceiling_dbtp"] == DENSE_CEILING_DBTP
    assert "sous 8 dB" in loud.treatments[-1].reason
    assert loud.checks.true_peak_dbtp <= DENSE_CEILING_DBTP + 0.05
    calm = master(x, FS, 1.0, tempo_bpm=140, target_lufs=-14.0)  # 12 dB of room: the usual ceiling
    assert calm.treatments[-1].measured["ceiling_dbtp"] == CEILING_DBTP
    assert calm.checks.integrated_lufs == pytest.approx(-14.0, abs=0.3)


def test_master_gain_search_respects_its_budget_and_says_so():
    x = beat(16, level=0.5) * 0.05  # very quiet and very peaky: −9 LUFS would need a huge reduction
    r = master(x, FS, 1.0, tempo_bpm=140)
    loud = r.treatments[-1].measured  # the budget holds for the recurring peaks and for isolated events
    assert loud["peak_reduction_db"] <= 9.0 + 0.1 and loud["single_peak_reduction_db"] <= 13.0 + 0.1
    if r.checks.integrated_lufs < TARGET_LUFS - 0.3:
        assert any("au lieu de" in w for w in r.warnings)


def test_small_intensity_changes_the_master_little():
    x = beat(16, level=0.3) + voice(16, seed=3) * 0.3
    r = master(x, FS, 0.02, tempo_bpm=95)
    assert abs(integrated_loudness(r.audio, FS) - integrated_loudness(x, FS)) < 0.6


def test_platform_playback():
    from eden.mix.master import checks
    t = np.arange(10 * FS) / FS
    quiet = np.stack([0.03 * np.sin(2 * np.pi * 440 * t)] * 2, 1)
    quiet[1000] = 1.2  # one peak above −1 dBTP: Spotify cannot raise it, and never lowers a quiet track
    spotify = next(p for p in checks(quiet, FS).platforms if p.name == "Spotify")
    assert spotify.gain_db == 0.0


def test_mono_holes_are_found_by_band():
    from eden.mix.master import mono_holes
    rng = np.random.default_rng(3)
    pad = dsp.split_band(rng.normal(0, 0.2, 12 * FS), FS, 250, 900)[0]
    x = beat(12) + np.stack([pad, -pad], 1)  # a polarity-flipped layer that disappears in mono
    holes = mono_holes(x, FS)
    third = 2 ** (1 / 6)  # every band found overlaps the flipped layer (250–900 Hz)
    assert holes and all(float(h.split()[0]) / third < 900 and float(h.split()[0]) * third > 250 for h in holes)
    assert mono_holes(beat(12), FS) == []


def test_master_keeps_the_stereo_low_end_mono():
    t = np.arange(int(12 * FS)) / FS
    wide = np.stack([np.sin(2 * np.pi * 50 * t), -np.sin(2 * np.pi * 50 * t)], axis=1) * 0.3 + beat(12)
    r = master(wide, FS, 1.0)
    assert any(t.kind == "mono_low" for t in r.treatments)
    assert stereo.low_band_correlation(wide, FS, 100.0) < 0.0 < r.checks.low_correlation


# -- full chain with FL Studio (simulator) ----------------------------------------

@pytest.fixture
def rendered(tmp_path):
    project = make_session(tmp_path)
    report = inspect_project(project, roots=SearchRoots())
    renders = render_project(project, sim_renderer(), timeout_s=120, report=report)
    assert renders.ok
    return project, report, renders


def test_eden_at_zero_gives_back_the_pre_master_song(rendered):
    project, report, renders = rendered
    version = mix_project(project, report, renders, intensity=0.0)
    a, _ = sf.read(renders.wav("premaster"))
    b, _ = sf.read(version.final_wav)
    assert np.max(np.abs(a - b[: a.shape[0]])) < 1e-9
    assert version.checks.integrated_lufs == pytest.approx(version.final.loudness_lufs)


def test_mix_versions_are_kept_with_their_decisions(rendered):
    project, report, renders = rendered
    steps = []
    a = mix_project(project, report, renders, intensity=1.0, on_step=lambda i, n, s: steps.append(i))
    b = mix_project(project, report, renders, intensity=0.5)
    assert steps == [0, 1, 2, 3]
    assert a.id != b.id
    assert a.final.loudness_lufs > a.original.loudness_lufs  # a loud master
    assert a.final.true_peak_db <= CEILING_DBTP + 0.05
    assert {p.fl_space for p in a.parts if p.role in ("lead_vocal", "adlib")} == {"tracked"}
    versions = list_versions(project)
    assert [v["id"] for v in versions] == [b.id, a.id]
    assert any(t["reason"] for p in versions[1]["parts"] for t in p["treatments"])
    assert versions[1]["song"]["tempo_bpm"] == 120.0 and versions[1]["checks"]["platforms"]
    folder = Path(a.final_wav).parent
    assert sorted(p.name for p in folder.iterdir()) == ["final.wav", "version.json"]
    assert not list(Path(os.environ["EDEN_HOME"]).rglob("*.flp"))


def test_mix_refuses_unverified_renders(rendered):
    project, report, renders = rendered
    renders.null_test.passed = False
    with pytest.raises(MixError, match="vérifications"):
        mix_project(project, report, renders)


def test_mix_refuses_a_project_changed_since_rendering(rendered):
    project, report, renders = rendered
    with open(project, "ab") as fh:
        fh.write(b"\0")
    with pytest.raises(MixError, match="changé"):
        mix_project(project, report, renders)


def test_parts_split_keeps_the_dry_voices(rendered):
    project, report, renders = rendered
    parts = split(report, renders)
    assert all(v.dry is not None for v in parts.voices)


# -- export --------------------------------------------------------------------------

def test_export_formats_and_safety(tmp_path):
    src = tmp_path / "final.wav"
    sf.write(src, np.stack([sine(440, 2, 44100, 0.5)] * 2, 1), 44100, subtype="FLOAT")
    out = export_wav(src, tmp_path / "Mon son", 48000, 24)
    data, sr = sf.read(out.path)
    assert (sr, sf.info(out.path).subtype, out.resampled) == (48000, "PCM_24", True)
    assert data.shape[0] == pytest.approx(96000, abs=2)
    with pytest.raises(ExportError, match="existe déjà"):
        export_wav(src, tmp_path / "Mon son", 48000, 24)
    same = export_wav(src, tmp_path / "Mon son", None, 16, overwrite=True)
    assert (same.sample_rate, same.dithered, same.resampled) == (44100, True, False)


def test_export_conversion_is_clean_and_keeps_the_true_peak(tmp_path):
    t = np.arange(4 * 48000) / 48000
    # 15 kHz must pass untouched; 23 kHz would fold back to 21.1 kHz at 44.1 kHz
    tones = np.sin(2 * np.pi * 15000 * t) * 0.3 + np.sin(2 * np.pi * 23000 * t) * 0.3
    src = tmp_path / "final.wav"
    sf.write(src, np.stack([tones] * 2, 1), 48000, subtype="FLOAT")
    out = export_wav(src, tmp_path / "44k", 44100, 32)
    data, sr = sf.read(out.path)
    spectrum = np.abs(np.fft.rfft(data[44100:3 * 44100, 0] * np.hanning(2 * 44100)))
    freqs = np.fft.rfftfreq(2 * 44100, 1 / 44100)

    def level(f):
        return 20 * math.log10(spectrum[np.abs(freqs - f) < 3].max())

    assert level(21100) < level(15000) - 95

    # read on the new sample grid, this tone's true peak comes out 0.1 dB higher: the limiter takes it back
    t = np.arange(44100) / 44100
    bright = 0.5 * np.sin(2 * np.pi * 16000 * t + math.pi / 6) * np.hanning(t.size)
    master = tmp_path / "master.wav"
    sf.write(master, np.stack([bright] * 2, 1), 44100, subtype="FLOAT")
    converted = export_wav(master, tmp_path / "48k", 48000, 32)
    assert converted.true_peak_dbtp <= true_peak_db(bright, 44100) + 0.02


def test_export_refuses_clipping_in_integer_formats(tmp_path):
    src = tmp_path / "chaud.wav"
    sf.write(src, np.stack([sine(440, 1, 44100, 1.4)] * 2, 1), 44100, subtype="FLOAT")
    with pytest.raises(ExportError, match="32 bits"):
        export_wav(src, tmp_path / "a", None, 24)
    assert not (tmp_path / "a.wav").exists()
    assert export_wav(src, tmp_path / "b", None, 32).bit_depth == 32
