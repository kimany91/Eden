"""Eden's mixing engine: measurements, processors, rules, full chain and export."""

import math
import os
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from scipy.signal import sosfreqz

from eden.mix import dsp
from eden.mix.analysis import measure_vocal
from eden.mix.engine import Part, apply, mix, plan_vocal
from eden.mix.export import ExportError, export_wav
from eden.mix.loudness import integrated_loudness, k_weighting, true_peak_db
from eden.mix.session import MixError, list_versions, mix_project
from eden.project.inspector import inspect_project
from eden.project.sources import SearchRoots
from eden.render.pipeline import render_project
from eden.render.verify import null_test
from synth_voice import FS, beat, voice
from test_render import make_session, sim_renderer


def sine(f, seconds=10.0, fs=48000, amp=1.0, phase=0.0):
    return amp * np.sin(2 * np.pi * f * np.arange(int(seconds * fs)) / fs + phase)


# -- loudness (ITU-R BS.1770) -----------------------------------------------------

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
    assert true_peak_db(x) == pytest.approx(0.0, abs=0.3)
    assert 20 * math.log10(np.max(np.abs(x))) == pytest.approx(-3.01, abs=0.01)


# -- processors ------------------------------------------------------------------------

def _gain_db(sos, f, fs=44100):
    _, h = sosfreqz(sos, worN=[f], fs=fs)
    return 20 * math.log10(abs(h[0]))


def test_filters():
    assert _gain_db(dsp.highpass_sos(44100, 80), 30) < -15
    assert _gain_db(dsp.highpass_sos(44100, 80), 1000) == pytest.approx(0, abs=0.1)
    assert _gain_db(dsp.peaking_sos(44100, 2500, 6, -3), 2500) == pytest.approx(-3, abs=0.05)
    assert _gain_db(dsp.peaking_sos(44100, 2500, 6, -3), 1000) == pytest.approx(0, abs=0.2)


def test_band_split_is_exact():
    x = np.random.default_rng(0).normal(0, 0.1, (FS * 2, 2))
    for lo, hi in ((1500, 4000), (4500, None), (None, 200)):
        band, rest = dsp.split_band(x, FS, lo, hi)
        assert np.max(np.abs(band + rest - x)) < 1e-12


def test_processors_at_zero_change_nothing():
    x = voice(seconds=6)
    assert dsp.compress(x, FS, -20, 1.0) is x
    assert dsp.deess(x, FS, -30, 0.0) is x
    env, size = dsp.activity_envelope(x, FS, -40)
    assert dsp.dip_band_when(x, FS, env, size, 0.0) is x


def test_compressor_reduces_loud_parts_only():
    quiet, loud = sine(1000, 2, FS, 0.05), sine(1000, 2, FS, 0.5)
    x = np.concatenate([quiet, loud])
    y = dsp.compress(x, FS, threshold_db=-20, ratio=4, knee_db=0)
    q = slice(FS // 2, FS + FS // 2)
    lo = slice(2 * FS + FS // 2, 3 * FS + FS // 2)
    assert np.max(np.abs(y[q])) == pytest.approx(0.05, rel=0.01)  # under threshold: untouched
    # 0.5 peak = −9 dB RMS-ish: 11 dB over threshold → about 8 dB of reduction at 4:1
    assert 20 * math.log10(np.max(np.abs(y[lo])) / 0.5) == pytest.approx(-8.3, abs=1.0)


def test_deesser_only_touches_the_high_band():
    x = voice(sibilance=1.5, seconds=8)
    change = dsp.deess(x, FS, threshold_db=-40, max_reduction_db=8) - x
    low_change, _ = dsp.split_band(change, FS, None, 2000)
    assert np.sum(change ** 2) > 1e-3
    assert np.sum(low_change ** 2) < 0.01 * np.sum(change ** 2)


# -- rules on voices with known defects ---------------------------------------------

@pytest.mark.parametrize("name,kwargs", [
    ("voix propre", {}),
    ("Auto-Tune sur deux notes", {"notes": [131, 147], "seed": 3}),
])
def test_a_clean_voice_is_left_alone(name, kwargs):
    assert plan_vocal(measure_vocal(voice(**kwargs), FS), "lead_vocal", 1.0) == []


@pytest.mark.parametrize("kwargs,kind,check", [
    ({"resonance_hz": 2500, "seed": 4}, "eq_cut", lambda t: abs(t.params["freq_hz"] - 2500) < 150),
    ({"rumble": 0.08, "seed": 5}, "highpass", lambda t: t.params["freq_hz"] == 80),
    ({"sibilance": 1.2, "seed": 6}, "deesser", lambda t: t.params["max_reduction_db"] > 0),
    ({"phrase_spread_db": 16, "seed": 7}, "compressor", lambda t: t.params["ratio"] > 1.5),
])
def test_each_defect_gets_its_treatment(kwargs, kind, check):
    treatments = plan_vocal(measure_vocal(voice(**kwargs), FS), "lead_vocal", 1.0)
    assert [t.kind for t in treatments] == [kind]
    assert check(treatments[0]) and treatments[0].reason


def test_treatments_fix_what_they_target():
    sib = voice(sibilance=1.2, seed=6)
    m = measure_vocal(sib, FS)
    after = measure_vocal(apply(sib, FS, plan_vocal(m, "lead_vocal", 1.0)), FS)
    assert after.sibilant_excess_db < m.sibilant_excess_db - 3

    dyn = voice(phrase_spread_db=16, seed=7)
    m = measure_vocal(dyn, FS)
    after = measure_vocal(apply(dyn, FS, plan_vocal(m, "lead_vocal", 1.0)), FS)
    assert after.dynamic_spread_db < m.dynamic_spread_db - 3


def test_intensity_scales_the_treatments():
    m = measure_vocal(voice(sibilance=1.2, seed=6), FS)
    full = plan_vocal(m, "lead_vocal", 1.0)[0].params["max_reduction_db"]
    half = plan_vocal(m, "lead_vocal", 0.5)[0].params["max_reduction_db"]
    assert half == pytest.approx(full / 2)
    assert plan_vocal(m, "lead_vocal", 0.0) == []


def _song():
    lead, adlib, instru = voice(seed=11) * 0.25, voice(seed=12, notes=[220, 247]) * 0.6, beat()
    return lead, adlib, instru, lead + adlib + instru


def test_mix_at_zero_is_exactly_the_original():
    lead, adlib, instru, premaster = _song()
    out = mix([Part("ch0", "Lead", "lead_vocal", lead), Part("ch1", "Adlib", "adlib", adlib)],
              Part("rest", "Reste", "rest", instru), FS, 0.0, integrated_loudness(premaster, FS))
    assert np.array_equal(out.premaster, premaster)
    assert all(not p.treatments for p in out.parts) and out.staging_gain_db == 0.0


def test_mix_balances_voices_and_keeps_the_master_input_level():
    lead, adlib, instru, premaster = _song()
    target = integrated_loudness(premaster, FS)
    out = mix([Part("ch0", "Lead", "lead_vocal", lead), Part("ch1", "Adlib", "adlib", adlib)],
              Part("rest", "Reste", "rest", instru), FS, 1.0, target)
    parts = {p.key: p for p in out.parts}
    lead_gain = [t for t in parts["ch0"].treatments if t.kind == "gain"]
    assert lead_gain and lead_gain[0].params["gain_db"] > 0  # buried lead brought up
    adlib_gain = [t for t in parts["ch1"].treatments if t.kind == "gain"]
    # the ad-lib was 8 dB above the lead: brought down, by no more than the 4 dB limit
    assert adlib_gain and adlib_gain[0].params["gain_db"] == pytest.approx(-4.0)
    before = parts["ch1"].loudness_before - parts["ch0"].loudness_before
    after = parts["ch1"].loudness_after - parts["ch0"].loudness_after
    assert after < before - 6
    assert [t.kind for t in parts["rest"].treatments] == ["presence_dip"]
    assert out.loudness_mix == pytest.approx(target, abs=0.05)


# -- full chain with FL Studio (simulator) ----------------------------------------

@pytest.fixture
def rendered(tmp_path):
    project = make_session(tmp_path)
    report = inspect_project(project, roots=SearchRoots())
    renders = render_project(project, sim_renderer(), timeout_s=120, report=report)
    assert renders.ok
    return project, report, renders


def test_eden_at_zero_through_the_fl_master_gives_back_the_song(rendered):
    project, report, renders = rendered
    version = mix_project(project, report, renders, sim_renderer(), intensity=0.0, timeout_s=120)
    assert null_test(renders.wav("original"), [Path(version.final_wav)]).residual_db < -100


def test_mix_versions_are_kept_with_their_decisions(rendered):
    project, report, renders = rendered
    steps = []
    a = mix_project(project, report, renders, sim_renderer(), intensity=1.0, timeout_s=120,
                    on_step=lambda i, n, s: steps.append(i))
    b = mix_project(project, report, renders, sim_renderer(), intensity=0.5, timeout_s=120)
    assert steps == [0, 1, 2, 3]
    assert a.id != b.id
    assert a.final.loudness_lufs == pytest.approx(a.original.loudness_lufs, abs=1.0)
    versions = list_versions(project)
    assert [v["id"] for v in versions] == [b.id, a.id]
    assert any(t["reason"] for p in versions[1]["parts"] for t in p["treatments"])
    folder = Path(a.final_wav).parent
    assert sorted(p.name for p in folder.iterdir()) == ["final.wav", "version.json"]
    assert not list(Path(os.environ["EDEN_HOME"]).rglob("*.flp"))


def test_mix_refuses_unverified_renders(rendered):
    project, report, renders = rendered
    renders.null_test.passed = False
    with pytest.raises(MixError, match="vérifications"):
        mix_project(project, report, renders, sim_renderer(), timeout_s=120)


def test_mix_refuses_a_project_changed_since_rendering(rendered):
    project, report, renders = rendered
    with open(project, "ab") as fh:
        fh.write(b"\0")
    with pytest.raises(MixError, match="changé"):
        mix_project(project, report, renders, sim_renderer(), timeout_s=120)


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


def test_export_refuses_clipping_in_integer_formats(tmp_path):
    src = tmp_path / "chaud.wav"
    sf.write(src, np.stack([sine(440, 1, 44100, 1.4)] * 2, 1), 44100, subtype="FLOAT")
    with pytest.raises(ExportError, match="32 bits"):
        export_wav(src, tmp_path / "a", None, 24)
    assert not (tmp_path / "a.wav").exists()
    assert export_wav(src, tmp_path / "b", None, 32).bit_depth == 32
