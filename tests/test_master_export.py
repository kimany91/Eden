"""Eden's mastering and export, checked by measurement: true peak, limiter, peak-reduction budget,
checks, gain search, export names, and how the measured reductions are reported."""

import math
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf
from scipy.signal import butter, sosfilt

from eden import cli
from eden.gui import viewmodel
from eden.mix import dsp
from eden.mix import master as M
from eden.mix.export import export_wav
from eden.mix.limiter import gain_for, limit
from eden.mix.loudness import integrated_loudness
from eden.mix.oversampling import PEAK_CONTEXT, PEAK_CORE, _continuous_max, peak_envelope, true_peak
from eden.mix.treatments import Treatment
from synth_voice import FS, beat, voice


def db(value):
    return 20 * math.log10(value)


def _spectrum(x, nfft):
    spectrum = np.fft.rfft(x, nfft, axis=0)
    spectrum[-1] *= 0.5  # the Nyquist bin is shared with its mirror image in the longer spectrum
    return spectrum


def reference_peak(x, up=64):
    """Peak of the waveform rebuilt by one 64× FFT over the whole signal (zero-padded by at
    least a quarter), channel by channel."""
    x = x if x.ndim == 2 else x[:, None]
    n = x.shape[0]
    nfft = 1 << int(math.ceil(math.log2(n + n // 4)))
    best = 0.0
    for c in range(x.shape[1]):
        y = np.fft.irfft(_spectrum(x[:, c].astype(np.float32), nfft), nfft * up) * up
        best = max(best, float(np.abs(y[:n * up]).max()))
    return best


def whole_envelope(x, factor=8):
    """``peak_envelope`` computed in one transform over the whole signal (no blocks)."""
    x = x if x.ndim == 2 else x[:, None]
    n = x.shape[0]
    nfft = 1 << int(math.ceil(math.log2(2 * n)))
    up = np.fft.irfft(_spectrum(x.astype(np.float32), nfft), nfft * factor, axis=0)
    return _continuous_max(up, 0, n, factor) * factor


def mix(seconds=16.0, seed=2):
    """Voice, beat and a decaying 808 (the verifier's synthetic song)."""
    rng = np.random.default_rng(seed)
    n = int(seconds * FS)
    sub = np.zeros(n)
    note = int(0.857 * FS)
    t = np.arange(note) / FS
    for start in range(0, n - note, note):
        f = rng.choice([41.2, 43.65, 49.0, 55.0])
        sub[start:start + note] += 10 ** (rng.uniform(-1, 1) / 20) * np.exp(-t / 0.6) * np.sin(2 * np.pi * f * t)
    sub *= 0.5
    return voice(seconds, seed=11, level=0.3) + beat(seconds, level=0.3) + np.stack([sub, sub], 1)


# -- true peak ------------------------------------------------------------------------------

@pytest.mark.parametrize("seed", [0, 7])
def test_true_peak_is_the_peak_of_the_continuous_waveform(seed):
    rng = np.random.default_rng(seed)
    n = 250000  # three true-peak blocks
    t = np.arange(n) / FS
    square = np.clip(3 * np.sin(2 * np.pi * rng.uniform(800, 9000) * t + rng.uniform(0, 6)), -1, 1)
    for x in (rng.normal(0, 0.2, (n, 2)), np.stack([square, 0.7 * square], 1)):
        assert abs(db(true_peak(x)) - db(reference_peak(x))) < 0.01


def test_true_peak_between_the_8x_points():
    # a band-limited click whose crest sits half-way between two of the 8 interpolated points
    k = np.arange(-3000, 3000)
    x = np.sinc(k - 1 / 16) * np.hanning(k.size)
    nfft = 1 << 14
    grid = np.abs(np.fft.irfft(_spectrum(x, nfft), nfft * 8) * 8).max()
    assert db(grid) < db(reference_peak(x)) - 0.04  # the plain 8× grid misses the crest
    assert abs(db(true_peak(x)) - db(reference_peak(x))) < 0.01


@pytest.mark.parametrize("n", [32768, 61440, 65536, PEAK_CORE + (1 << 16) - PEAK_CONTEXT])
def test_peak_envelope_does_not_wrap_the_end_of_the_song(n):
    # the block that reaches the end is a power of two long (or nearly): without zeros after it,
    # the circular interpolation rings the last samples against the block's first ones
    rng = np.random.default_rng(1)
    x = rng.normal(0, 0.3, (n, 2))
    assert np.abs(peak_envelope(x) - whole_envelope(x)).max() < 0.01
    loud = 0.9 * np.sin(2 * np.pi * 997 * np.arange(n) / FS)  # loud up to the very last sample
    end = slice(n - 2000, n)
    assert np.abs(20 * np.log10(peak_envelope(loud)[end] / whole_envelope(loud)[end])).max() < 0.05


def test_limiter_holds_the_ceiling_for_the_continuous_peak():
    x = (beat(3) + voice(3) * 0.8) * 3.0
    result = limit(x, FS, ceiling_dbtp=-1.0)
    assert db(reference_peak(result.audio)) <= -1.0
    assert result.true_peak_db <= -1.0


@pytest.mark.parametrize("g", [0.5, 0.707, 0.891])
def test_limiter_gain_never_jumps(g):
    # one sample needs gain g, wherever it falls in a 1 ms release frame (the verifier's case)
    worst = 0.0
    for offset in range(44):
        peak = np.full(20000, 0.5)
        peak[8000 + offset] = 0.5 / g
        gain = gain_for(peak, 44100, 0.5)
        assert np.all(gain <= np.minimum(1.0, 0.5 / peak) + 1e-12)  # no peak gets through
        worst = max(worst, np.abs(np.diff(gain)).max())
    assert worst < 0.01


# -- peak-reduction budget ------------------------------------------------------------------

def test_budget_statistic_ignores_short_events():
    before = np.ones(3000)  # 30 s of 10 ms blocks, every peak reduced by 7 dB
    after = before / 10 ** (7 / 20)
    click = before.copy()
    click[1500] *= 10 ** (8 / 20)  # one 10 ms block taken 15 dB down
    red = M._peak_reduction(click, after, 0.0, 0.0)
    assert red.recurring_db == pytest.approx(7.0) and red.single_db == pytest.approx(7.0)
    assert red.over_db < 0
    hit = before.copy()
    hit[1500:1503] *= 10 ** (8 / 20)  # 30 ms taken 15 dB down: an isolated event, over its limit
    red = M._peak_reduction(hit, after, 0.0, 0.0)
    assert red.recurring_db == pytest.approx(7.0) and red.single_db == pytest.approx(15.0)
    assert red.isolated and red.over_db == pytest.approx(15.0 - 13.0) and red.single_at_s == pytest.approx(15.0)
    recurring = before.copy()
    recurring[::50] *= 10 ** (4 / 20)  # a hit every 0.5 s, 11 dB down: the drums' job
    red = M._peak_reduction(recurring, after, 0.0, 0.0)
    assert red.recurring_db == pytest.approx(11.0) and not red.isolated and red.over_db == pytest.approx(2.0)


def _impact(x, ms, rel_db, kind, rng):
    n = int(ms * FS / 1000)
    t = np.arange(n) / FS
    if kind == "noise":
        hit = rng.normal(0, 1, n) * np.exp(-t / (ms / 1000 / 4))
    else:
        hit = np.sin(2 * np.pi * 60 * t) * np.exp(-t / (ms / 1000 / 3))
    y = x.copy()
    y[8 * FS:8 * FS + n] += np.abs(x).max() * 10 ** (rel_db / 20) * (hit / np.abs(hit).max())[:, None]
    return y


@pytest.fixture(scope="module")
def plain_and_outliers():
    """The verifier's cases: the song, then the same song with one click, one kick or one crash
    louder than everything else in it. Each master's number of full passes is kept too."""
    x = mix()
    rng = np.random.default_rng(5)
    cases = {"plain": x, "click 1 ms +6 dB": _impact(x, 1, 6, "sine", rng),
             "kick 60 ms +3 dB": _impact(x, 60, 3, "sine", rng),
             "crash 200 ms +3 dB": _impact(x, 200, 3, "noise", rng)}
    real = M._loud_stage
    out = {}
    for name, y in cases.items():
        calls = []
        M._loud_stage = lambda *a, _calls=calls: _calls.append(a[2]) or real(*a)
        try:
            out[name] = (M.master(y, FS, 1.0, tempo_bpm=140), len(calls))
        finally:
            M._loud_stage = real
    return out


def test_one_short_event_does_not_set_the_loudness_of_the_song(plain_and_outliers):
    plain, _ = plain_and_outliers["plain"]
    assert plain.checks.integrated_lufs == pytest.approx(M.TARGET_LUFS, abs=0.2) and not plain.warnings
    for name, (r, passes) in plain_and_outliers.items():
        ceiling = r.treatments[-1].measured["ceiling_dbtp"]
        assert r.checks.integrated_lufs == pytest.approx(plain.checks.integrated_lufs, abs=0.5), name
        assert r.checks.true_peak_dbtp <= ceiling, name
        assert not any("percussions" in w for w in r.warnings), name
        assert passes <= M.REAL_PASSES, name
    click, _ = plain_and_outliers["click 1 ms +6 dB"]
    loud = click.treatments[-1].measured
    assert loud["clip_db"] > M.MAX_PEAK_REDUCTION_DB  # the click itself is clipped hard, and shown
    assert loud["peak_reduction_db"] <= M.MAX_PEAK_REDUCTION_DB + 0.1
    assert f"crête la plus forte baissée de {loud['clip_db']:.1f} dB" in click.treatments[-1].reason


def test_gain_search_reaims_on_the_proxy_after_one_pass(monkeypatch):
    # a stand-in chain: loudness follows the gain exactly, the proxy reads 0.5 LU too low, and the
    # recurring peaks are reduced by (gain − 3) dB, so the budget stops the gain at 12 dB
    x = beat(4) * 0.1
    before = integrated_loudness(x, FS)
    stages = []

    def stage(y, fs, gain, ceiling):
        stages.append(gain)
        return y * 10 ** (gain / 20), M.PeakReduction(0.0, 0.0, gain - 3.0, 0.0, 0.0)

    monkeypatch.setattr(M, "_loud_stage", stage)
    monkeypatch.setattr(M, "_proxy_loudness", lambda y, fs, gain, c: before + gain - 0.5)
    out, gain, red, reached, capped = M._loudest(x, FS, before + 10.0, -3.0)
    assert len(stages) == 2 and reached == pytest.approx(before + 10.0, abs=0.15) and not capped
    stages.clear()
    out, gain, red, reached, capped = M._loudest(x, FS, before + 14.0, -3.0)  # needs 14 dB: over budget
    assert stages[1] == pytest.approx(12.0, abs=0.06) and len(stages) <= M.REAL_PASSES
    assert capped and red.over_db <= 0.1 and reached == pytest.approx(before + 12.0, abs=0.1)


def _hits(seconds=12, every_s=0.5):
    """A 60 Hz hit every half second over a quiet tone: the peaks recur, the loudness is low."""
    n = seconds * FS
    x = 10 ** (-30 / 20) * np.sin(2 * np.pi * 220 * np.arange(n) / FS)
    t = np.arange(int(0.08 * FS)) / FS
    hit = np.exp(-t / 0.02) * np.sin(2 * np.pi * 60 * t)
    for start in range(0, n - t.size, int(every_s * FS)):
        x[start:start + t.size] += hit
    return np.stack([x, x], 1) * 0.5


@pytest.mark.parametrize("song, ceiling", [
    (beat(16, level=0.5) * 0.05, M.DENSE_CEILING_DBTP),  # stopped near −10.5 LUFS: −2 dBTP would be dense
    (_hits(), M.CEILING_DBTP),  # stopped far under: −2 dBTP leaves 8 dB or more
])
def test_a_capped_master_chooses_its_ceiling_on_the_loudness_reached(song, ceiling):
    r = M.master(song, FS, 1.0, tempo_bpm=140)
    loud = r.treatments[-1].measured
    reached = r.checks.integrated_lufs
    assert reached < M.TARGET_LUFS - 0.2
    assert loud["peak_reduction_db"] <= M.MAX_PEAK_REDUCTION_DB + 0.1
    assert loud["single_peak_reduction_db"] <= M.MAX_PEAK_REDUCTION_DB + M.SINGLE_PEAK_MARGIN_DB + 0.1
    warning = next(w for w in r.warnings if "au lieu de" in w)
    assert f"masterisé à {reached:.1f} LUFS" in warning and "crêtes qui reviennent" in warning
    assert loud["ceiling_dbtp"] == ceiling and r.checks.true_peak_dbtp <= ceiling
    shift = M.CEILING_DBTP - M.DENSE_CEILING_DBTP  # at −2 dBTP the same master is 1 dB louder
    if ceiling == M.CEILING_DBTP:
        assert M.CEILING_DBTP - reached >= M.DENSE_PLR_DB
        assert f"laisse {M.CEILING_DBTP - reached:.1f} dB entre crête et volume : pas assez dense" in \
            r.treatments[-1].reason
    else:
        assert M.CEILING_DBTP - (reached + shift) < M.DENSE_PLR_DB
        assert f"ce master monterait à {reached + shift:.1f} LUFS" in r.treatments[-1].reason


def test_a_master_capped_just_under_its_goal_keeps_the_dense_ceiling_and_says_why(monkeypatch):
    # stopped 0.3 LU under −9 LUFS by one isolated event: at −2 dBTP the same budget would allow
    # 1 dB more, so that master would reach the goal itself (not 0.7 LU above it), still dense
    x = mix(6.0)
    red = M.PeakReduction(6.0, 2.0, 7.2, 13.2, 3.0)
    monkeypatch.setattr(M, "_loudest", lambda y, fs, goal, ceiling: (y, 8.0, red, goal - 0.3, True))
    r = M.master(x, FS, 1.0, tempo_bpm=140)
    loud = r.treatments[-1]
    assert loud.measured["ceiling_dbtp"] == M.DENSE_CEILING_DBTP
    assert "ce master monterait à -9.0 LUFS et laisserait au plus 7.0 dB entre crête et volume" in loud.reason
    assert "plus forte baisse tenue sur 30 ms de suite est de 13.2 dB (13 dB au plus" in loud.reason
    assert any("masterisé à -9.3 LUFS" in w and "crête isolée vers 0:03" in w for w in r.warnings)


def test_dense_ceiling_reason_does_not_round_its_figure():
    r = M.master(mix(6.0), FS, 1.0, tempo_bpm=140, target_lufs=-9.6)
    assert "laisserait au plus 7.6 dB entre crête et volume : sous 8 dB" in r.treatments[-1].reason


# -- checks -----------------------------------------------------------------------------------

def test_plr_warning_follows_the_planned_ratio(monkeypatch):
    real = M.checks

    def with_plr(plr):
        def fake(x, fs):
            c = real(x, fs)
            c.plr_db = plr
            return c
        return fake

    x = mix(6.0)
    monkeypatch.setattr(M, "checks", with_plr(5.9))  # on target at −9 LUFS / −3 dBTP: 6 dB planned
    assert not any("crête/volume" in w for w in M.master(x, FS, 1.0, tempo_bpm=140).warnings)
    monkeypatch.setattr(M, "checks", with_plr(5.4))
    assert any("Rapport crête/volume de 5.4 dB, sous 5.5 dB" in w
               for w in M.master(x, FS, 1.0, tempo_bpm=140).warnings)


def test_a_calm_master_is_not_called_dense():
    rng = np.random.default_rng(1)
    noise = sosfilt(butter(2, [60, 5000], btype="bandpass", fs=FS, output="sos"), rng.normal(0, 1, (8 * FS, 2)),
                    axis=0)
    x = np.clip(noise / noise.std() * 0.05, -0.25, 0.25)
    r = M.master(x, FS, 1.0, tempo_bpm=140, target_lufs=-14.0)
    assert 7.5 < r.checks.plr_db < 11.5  # under −2 dBTP − (−14 LUFS) − 0.5, but not under 8 dB
    assert not any("crête/volume" in w for w in r.warnings)


def test_wide_decorrelated_sound_is_not_a_mono_hole():
    rng = np.random.default_rng(0)
    pad = dsp.split_band(rng.normal(0, 0.2, (60 * FS, 2)), FS, 150, 3000)[0]  # two independent sides
    assert M.mono_holes(pad, FS) == []


def test_a_polarity_flipped_part_is_a_mono_hole():
    rng = np.random.default_rng(3)
    song = beat(20)
    flipped = dsp.split_band(rng.normal(0, 0.2, 4 * FS), FS, 250, 900)[0]
    song[8 * FS:12 * FS] += np.stack([flipped, -flipped], 1)  # 4 s that vanish in mono
    holes = M.mono_holes(song, FS)
    third = 2 ** (1 / 6)
    assert holes and all(float(h.split()[0]) / third < 900 and float(h.split()[0]) * third > 250 for h in holes)


# -- export ----------------------------------------------------------------------------------

@pytest.mark.parametrize("name, expected", [
    ("Beat v1.2 - Eden", "Beat v1.2 - Eden.wav"),
    ("Freestyle (prod. Kabe) - Eden", "Freestyle (prod. Kabe) - Eden.wav"),
    ("Vol. 2 - Eden", "Vol. 2 - Eden.wav"),
    ("Song.wav", "Song.wav"),
])
def test_export_keeps_every_dot_of_the_name(tmp_path, name, expected):
    src = tmp_path / "final.wav"
    sf.write(src, np.zeros((4410, 2)), FS, subtype="FLOAT")
    result = export_wav(src, tmp_path / name, None, 24)
    assert result.path == str(tmp_path / expected)
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(["final.wav", expected])


def test_export_names_that_differ_after_a_dot_do_not_collide(tmp_path):
    src = tmp_path / "final.wav"
    sf.write(src, np.zeros((4410, 2)), FS, subtype="FLOAT")
    export_wav(src, tmp_path / "Beat v1.2 - Eden", None, 24)
    export_wav(src, tmp_path / "Beat v1.3 - Eden", None, 24)
    assert (tmp_path / "Beat v1.2 - Eden.wav").is_file() and (tmp_path / "Beat v1.3 - Eden.wav").is_file()


# -- what the user is shown ------------------------------------------------------------------

def test_measured_reductions_are_shown():
    comp = Treatment("compressor", "Compression des crêtes 4.0:1", "Facteur de crête 14 dB",
                     measured={"reduction_mean_db": 1.24, "reduction_max_db": 3.46})
    eq = Treatment("eq", "Résonance 3150 Hz -2.0 dB", "Bosse de 5 dB", measured={})
    text = "Réduction mesurée : 1.2 dB en moyenne quand il agit, 3.5 dB au plus"
    assert viewmodel.reduction_text(comp.kind, comp.measured) == text
    assert viewmodel.reduction_text(eq.kind, eq.measured) == ""
    assert viewmodel.reduction_text("loudness", {"clip_db": 6.0}) == ""
    version = {
        "id": "v", "created_at": "2026-01-01T00:00:00+00:00", "intensity": 1.0, "final_wav": "f.wav",
        "parts": [{"label": "Lead", "role": "lead_vocal", "treatments": [vars(comp), vars(eq)],
                   "loudness_before": -20.0, "loudness_after": -19.0}],
        "master": [vars(comp)], "checks": None,
        "original": {"loudness_lufs": -12.0, "true_peak_db": -1.0},
        "final": {"loudness_lufs": -9.0, "true_peak_db": -3.0, "sample_rate": 44100},
    }
    view = viewmodel.mix_view(version)
    assert [t["measured"] for t in view["parts"][0]["treatments"]] == [text, ""]
    assert view["master"][0]["measured"] == text


def test_eden_mix_prints_the_measured_reductions(capsys):
    comp = Treatment("deesser", "De-esser principal (max 4.0 dB)", "Les « s » montent à -2.0 dB",
                     measured={"reduction_mean_db": 2.04, "reduction_max_db": 3.96})
    checks = SimpleNamespace(integrated_lufs=-9.0, true_peak_dbtp=-3.0, loudness_range_lu=4.0, plr_db=6.0,
                             platforms=[])
    version = SimpleNamespace(
        song=SimpleNamespace(key=None, key_confidence=None, tempo_bpm=None, bass_root=None),
        parts=[SimpleNamespace(label="Lead", treatments=[comp], space=[], placement=None)],
        master=[comp], checks=checks, original=SimpleNamespace(loudness_lufs=-12.0, true_peak_db=-1.0),
        warnings=[])
    cli._print_version(version)
    out = capsys.readouterr().out
    assert out.count("    Réduction mesurée : 2.0 dB en moyenne quand il agit, 4.0 dB au plus") == 2


def test_cli_describes_what_eden_mix_does(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    text = " ".join(capsys.readouterr().out.split())  # argparse wraps the help to the terminal
    assert "Mixer les voix puis masteriser avec Eden (les effets du Master FL Studio ne sont pas utilisés)" in text
    for command in ("inspect", "fl-probe", "render", "mix", "gui", "update"):
        assert f"``eden {command}``" in cli.__doc__
