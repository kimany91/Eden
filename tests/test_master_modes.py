"""The mastering is the user's option (mix/master.py MasterSettings, settings.py, session.py):
``simple`` by default — peaks reduced and the level set for the platforms, nothing that
saturates — the full chain and its settings behind the mastering window, or no mastering at all."""

import pytest

from eden.mix import master as M
from eden.mix.loudness import felt_loudness
from eden.settings import Settings, load_settings, master_settings, save_settings
from synth_voice import FS, beat, voice


@pytest.fixture(scope="module")
def song():
    return 0.5 * beat(12, level=0.5) + voice(12, seed=3)


def test_the_simple_master_reduces_peaks_and_sets_the_level_without_saturating(song):
    r = M.master(song, FS, 1.0, tempo_bpm=140, settings=M.MasterSettings(mode="simple"))
    assert [t.kind for t in r.treatments] == ["master_mode", "loudness"]  # no bus comp, no mono fold
    assert r.clip_db == 0.0  # the soft clipper never runs: nothing saturates
    loud = r.treatments[-1]
    assert loud.label.startswith("Niveau final") and "limiteur à" in loud.label and "clip" not in loud.label
    assert "sans écrêtage doux (rien qui sature)" in loud.reason
    assert r.checks.true_peak_dbtp <= loud.measured["ceiling_dbtp"] + 0.01
    assert felt_loudness(r.audio, FS) > felt_loudness(song, FS) + 3.0  # the level was set for the platforms
    assert "fenêtre Mastering" in r.treatments[0].reason


def test_no_mastering_leaves_the_mix_untouched_and_warns_on_a_hot_peak(song):
    r = M.master(song, FS, 1.0, tempo_bpm=140, settings=M.MasterSettings(mode="aucun"))
    assert r.audio is song and [t.kind for t in r.treatments] == ["master_mode"]
    assert not r.warnings  # this mix peaks far under −1 dBTP
    hot = M.master(song * 10 ** ((-1.0 - r.checks.true_peak_dbtp + 0.8) / 20), FS, 1.0,
                   tempo_bpm=140, settings=M.MasterSettings(mode="aucun"))
    assert any("peut écrêter" in w for w in hot.warnings)  # above −1 dBTP: the platforms' codecs clip


def test_the_window_settings_steer_the_full_chain(song):
    bare = M.master(song, FS, 1.0, tempo_bpm=140,
                    settings=M.MasterSettings(mode="complet", bus_compression=False, soft_clip=False))
    assert "compressor" not in {t.kind for t in bare.treatments} and bare.clip_db == 0.0
    tight = M.master(song, FS, 1.0, tempo_bpm=140,
                     settings=M.MasterSettings(mode="complet", budget_db=4.0))
    assert tight.treatments[-1].measured["peak_reduction_db"] <= 4.1
    assert "(4 dB au plus" in tight.treatments[-1].reason
    fixed = M.master(song, FS, 1.0, tempo_bpm=140,
                     settings=M.MasterSettings(mode="complet", ceiling_dbtp=-2.0))
    assert fixed.treatments[-1].measured["ceiling_dbtp"] == -2.0
    assert "plafond fixé à -2 dBTP (ton choix" in fixed.treatments[-1].reason
    quiet = M.master(song, FS, 1.0, tempo_bpm=140,
                     settings=M.MasterSettings(mode="complet", target_lufs=-12.0))
    assert felt_loudness(quiet.audio, FS) == pytest.approx(-12.0, abs=0.3)


def test_a_finished_beat_keeps_its_lower_budget_whatever_the_window_asks(song):
    r = M.master(song, FS, 1.0, tempo_bpm=140, finished_beat=True,
                 settings=M.MasterSettings(mode="complet", budget_db=9.0))
    assert r.treatments[-1].measured["peak_reduction_db"] <= M.FINISHED_BEAT_PEAK_REDUCTION_DB + 0.1


def test_stored_choices_become_master_settings():
    s = Settings(master_mode="complet", master_target_lufs=-10.0, master_ceiling_dbtp=-2.0,
                 master_bus_compression=False, master_soft_clip=False, master_budget_db=4.5)
    built = master_settings(s)
    assert built == M.MasterSettings(mode="complet", target_lufs=-10.0, ceiling_dbtp=-2.0,
                                     bus_compression=False, soft_clip=False, budget_db=4.5)
    assert master_settings(Settings()).mode == "simple"  # the product's default
    assert master_settings(Settings(master_mode="n'importe quoi")).mode == "simple"
    save_settings(s)
    assert master_settings(load_settings()) == built  # survives the JSON round-trip (None ceiling too)
    save_settings(Settings())
    assert master_settings(load_settings()).ceiling_dbtp is None


def test_the_session_masters_simple_unless_told_otherwise(tmp_path, monkeypatch):
    from eden.mix import session
    from eden.mix.session import mix_project
    from eden.project.inspector import inspect_project
    from eden.project.sources import SearchRoots
    from eden.render.pipeline import render_project
    from test_render import make_session, sim_renderer

    project = make_session(tmp_path)
    report = inspect_project(project, roots=SearchRoots())
    renders = render_project(project, sim_renderer(), timeout_s=120, report=report)
    given = []
    real = session.master
    monkeypatch.setattr(session, "master",
                        lambda *a, **kw: given.append(kw["settings"]) or real(*a, **kw))
    mix_project(project, report, renders, 1.0)
    assert given == [M.MasterSettings()] and given[0].mode == "simple"
    mix_project(project, report, renders, 1.0,
                master_settings=M.MasterSettings(mode="aucun"))
    assert given[1].mode == "aucun"


def test_the_mastering_window_choices_are_kept_and_used(tmp_path, monkeypatch):
    QtGui = pytest.importorskip("PySide6.QtGui")
    import eden.mix.session as session_mod
    from test_gui import wait_idle
    from test_render import make_session, sim_renderer

    from eden.gui.controller import EdenController

    _app = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])
    c = EdenController(renderer_factory=sim_renderer, check_updates=False)
    c.masterMode = "complet"
    c.masterTarget = -10.0
    c.masterCeiling = -2.0
    c.masterCompression = False
    c.masterClip = False
    c.masterBudget = 4.0
    wanted = M.MasterSettings("complet", -10.0, -2.0, False, False, 4.0)
    assert master_settings(load_settings()) == wanted  # kept in settings.json...
    again = EdenController(renderer_factory=sim_renderer, check_updates=False)
    assert again.masterMode == "complet" and again.masterCeiling == -2.0 and not again.masterClip

    given = []
    real = session_mod.mix_project
    monkeypatch.setattr(session_mod, "mix_project",
                        lambda *a, **kw: given.append(kw["master_settings"]) or real(*a, **kw))
    c.openProject(str(make_session(tmp_path)))  # ...and handed to the mix (run at the journey's end)
    wait_idle(c, timeout_ms=180000)
    assert c.errorMessage == "", c.errorMessage
    assert c.mixResult and given == [wanted]
    c.masterMode = "n'importe quoi"  # an unknown mode is refused, the stored choice stays
    assert c.masterMode == "complet"


def test_the_simple_master_follows_the_intensity(song):
    half = M.master(song, FS, 0.5, tempo_bpm=140, settings=M.MasterSettings(mode="simple"))
    full = M.master(song, FS, 1.0, tempo_bpm=140, settings=M.MasterSettings(mode="simple"))
    before = felt_loudness(song, FS)
    assert felt_loudness(half.audio, FS) < felt_loudness(full.audio, FS)
    # at 50 % the goal sits halfway between the mix as it came in and the target (budget allowing)
    assert felt_loudness(half.audio, FS) <= before + (M.TARGET_LUFS - before) * 0.5 + 0.3
    off = M.master(song, FS, 0.0, settings=M.MasterSettings(mode="simple"))
    assert off.audio is song and off.treatments == []
