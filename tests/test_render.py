import json
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from eden.flp.edit import FlpEditError, FlpEditor
from eden.flp.events import read_events
from eden.flp.parser import parse_bytes
from eden.flp.writer import serialize
from eden.project.inspector import inspect_project
from eden.project.sources import SearchRoots
from eden.render import pipeline as pipeline_mod
from eden.render.fl_studio import FLStudioRenderer, RenderError
from eden.render.pipeline import render_project
from eden.render.plan import plan_renders
from eden.render.probe import probe_fl_studio
from eden.render.verify import null_test
from eden.settings import load_settings
from flp_builder import Chan, Clip, Insert, Slot, build_flp

SIM = str(Path(__file__).parent / "fl_simulator.py")
BAR = 96 * 4


def sim_renderer(args=("/R", "/Ewav", "{project}")):
    return FLStudioRenderer([sys.executable, SIM], list(args), name="simulateur")


class CountingRenderer:
    def __init__(self, inner):
        self.inner, self.calls, self.name = inner, 0, "compteur"

    def render(self, copy, timeout_s):
        self.calls += 1
        return self.inner.render(copy, timeout_s)


@pytest.fixture
def session(tmp_path):
    return make_session(tmp_path)


def make_session(tmp_path):
    """Lead + adlib into a vocal bus with reverb, an 808 also sent to that bus,
    a beat played straight into the Master, and a limiter on the Master."""
    d = tmp_path / "Session"
    for name in ("Lead.wav", "Adlib.wav", "Beat.wav", "808.wav"):
        d.mkdir(exist_ok=True)
        sf.write(d / name, np.zeros((4410, 2)), 44100)
    inserts = [
        Insert(routes=(), slots={0: Slot("Fruity Limiter")}),
        Insert(name="Voix lead", routes=(3,), slots={0: Slot("Fruity parametric EQ 2")}),
        Insert(name="Adlibs", routes=(3,)),
        Insert(name="Bus voix", routes=(0,), slots={0: Slot("Fruity Reeverb 2")}),
        Insert(name="Vide"),
        Insert(name="808", routes=(0, 3), slots={0: Slot("Fruity Fast Dist")}),
    ]
    channels = [
        Chan("Lead", insert=1, sample_path=str(d / "Lead.wav")),
        Chan("Adlib", insert=2, sample_path=str(d / "Adlib.wav")),
        Chan("Instru", insert=0, sample_path=str(d / "Beat.wav")),
        Chan("808", insert=5, sample_path=str(d / "808.wav")),
    ]
    clips = [Clip(1, 0, BAR * 2, channel=0), Clip(2, 0, BAR, channel=1),
             Clip(3, 0, BAR * 2, channel=2), Clip(4, 0, BAR * 2, channel=3)]
    flp = d / "Session.flp"
    flp.write_bytes(build_flp(channels, inserts, clips, tempo=120))
    return flp


def _report(path):
    return inspect_project(path, roots=SearchRoots())


# -- writer & editor -------------------------------------------------------------

def test_writer_round_trip_is_byte_exact(session):
    data = session.read_bytes()
    header, events = read_events(data)
    assert serialize(header, events) == data


def test_writer_round_trip_real_project(real_flp):
    data = real_flp.read_bytes()
    assert serialize(*read_events(data)) == data


def test_editor_changes_only_what_is_asked(session):
    original = session.read_bytes()
    ed = FlpEditor(original)
    ed.set_insert_enabled(2, False)
    ed.set_insert_effects_enabled(0, False)
    ed.set_channel_enabled(3, False)
    ed.set_sample_path(0, r"E:\Nouveau\Lead.wav")
    ed.set_route(5, 0, False)
    before, after = parse_bytes(original), parse_bytes(ed.to_bytes())
    assert after.insert(2).enabled is False and before.insert(2).enabled is True
    assert after.insert(0).effects_enabled is False
    assert after.channel(3).enabled is False
    assert after.channel(0).sample_path == r"E:\Nouveau\Lead.wav"
    assert [r.target for r in after.insert(5).routes] == [3]
    for idx in (1, 3, 4):
        assert after.insert(idx) == before.insert(idx)
    assert [c.name for c in after.channels] == [c.name for c in before.channels]
    assert len(ed.changes) == 5
    assert session.read_bytes() == original  # the file on disk is untouched


def test_editor_on_real_project(real_flp):
    ed = FlpEditor(real_flp.read_bytes())
    ed.set_insert_enabled(19, False)
    ed.set_channel_enabled(11, False)
    p = parse_bytes(ed.to_bytes())
    assert p.insert(19).enabled is False and p.insert(19).name == "Plugin Test"
    assert p.channel(11).enabled is False and p.channel(11).name == "22in Kick"


def test_editor_errors(session):
    ed = FlpEditor(session.read_bytes())
    with pytest.raises(FlpEditError):
        ed.set_insert_enabled(500, False)
    with pytest.raises(FlpEditError):
        ed.set_channel_enabled(42, False)


# -- plan ---------------------------------------------------------------------------

def test_render_plan(session):
    plan = plan_renders(_report(session))
    kinds = [j.kind for j in plan.jobs]
    assert kinds[:2] == ["original", "premaster"]
    stems = {j.name: j for j in plan.by_kind("stem")}
    assert set(stems) == {"stem-003-bus-voix", "stem-005-808", "stem-ch002-instru"}
    bus = stems["stem-003-bus-voix"]
    assert not {1, 2, 3, 5} & set(bus.mute_inserts)  # bus keeps everything feeding it
    assert stems["stem-005-808"].mute_inserts.count(3) == 1  # 808 stem: its send to the bus is muted
    assert bus.cut_routes == [(5, 0)]  # bus stem: the 808's direct route to the Master is cut
    assert all(j.bypass_master_effects for j in plan.jobs[1:])
    vocal = {j.name for j in plan.by_kind("vocal")}
    assert vocal == {"vocal-ch000-lead", "vocal-ch001-adlib"}
    assert any("plusieurs groupes" in n for n in plan.notes)


# -- full pipeline ---------------------------------------------------------------

def test_render_pipeline_reproduces_the_mix(session, tmp_path):
    original = session.read_bytes()
    renderer = CountingRenderer(sim_renderer())
    result = render_project(session, renderer, timeout_s=120, workspace_home=None)
    assert result.ok, (result.null_test, [j.error for j in result.jobs])
    assert result.null_test.residual_db < -100
    assert renderer.calls == len(result.plan.jobs) == 7
    # the Master limiter is in the original render but not in the pre-master one
    a, _ = sf.read(result.wav("original"))
    b, _ = sf.read(result.wav("premaster"))
    assert np.max(np.abs(a - b)) > 1e-3
    lead = sf.read(result.wav("vocal-ch000-lead"))[0]
    assert np.max(np.abs(lead)) > 0.01
    assert session.read_bytes() == original
    assert sorted(p.name for p in session.parent.iterdir()) == [
        "808.wav", "Adlib.wav", "Beat.wav", "Lead.wav", "Session.flp"]
    manifest = json.loads((Path(result.folder) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["null_test"]["passed"] is True

    # Second run: everything is reused, FL Studio is not launched again.
    again = CountingRenderer(sim_renderer())
    result2 = render_project(session, again, timeout_s=120)
    assert again.calls == 0
    assert {j.status for j in result2.jobs} == {"resumed"} and result2.ok


def test_wrong_stem_split_is_caught(session, monkeypatch):
    real_plan = pipeline_mod.plan_renders

    def plan_missing_a_stem(report):
        plan = real_plan(report)
        plan.jobs = [j for j in plan.jobs if j.name != "stem-005-808"]
        return plan

    monkeypatch.setattr(pipeline_mod, "plan_renders", plan_missing_a_stem)
    result = render_project(session, sim_renderer(), timeout_s=120)
    assert not result.null_test.passed and not result.ok


def test_moved_samples_are_repaired_in_copies(session, tmp_path):
    moved = tmp_path / "Ailleurs"
    session.parent.rename(moved)
    project = moved / "Session.flp"
    result = render_project(project, sim_renderer(), timeout_s=120)
    assert result.repairs and result.ok
    copy = parse_bytes(Path(result.jobs[0].copy_path).read_bytes())
    assert Path(copy.channel(0).sample_path).parent == moved


def test_missing_sample_stops_before_rendering(session):
    (session.parent / "Adlib.wav").unlink()
    with pytest.raises(RenderError, match="introuvables"):
        render_project(session, sim_renderer(), timeout_s=120)


def test_renderer_failure_is_explicit(session, monkeypatch):
    monkeypatch.setenv("EDEN_SIM_NO_OUTPUT", "1")
    with pytest.raises(RenderError, match="sans produire de fichier WAV"):
        render_project(session, sim_renderer(), timeout_s=120)


def test_renderer_timeout(session, tmp_path):
    slow = tmp_path / "slow.py"
    slow.write_text("import time; time.sleep(30)")
    renderer = FLStudioRenderer([sys.executable, str(slow)], ["{project}"])
    with pytest.raises(RenderError, match="pas terminé"):
        render_project(session, renderer, timeout_s=1)


# -- probe ------------------------------------------------------------------------

def _probe(session, tmp_path, **kw):
    settings = tmp_path / "settings.json"
    res = probe_fl_studio(session, command=[sys.executable, SIM], timeout_s=120,
                          settings_file=settings, log=lambda m: None, **kw)
    return res, load_settings(settings)


def test_probe_finds_working_syntax_and_saves_it(session, tmp_path):
    res, settings = _probe(session, tmp_path)
    assert res.ok and res.isolation_channels_ok and res.isolation_inserts_ok and res.isolation_routes_ok
    assert settings.render_args == ["/R", "/Ewav", "{project}"]
    assert "FLOAT" in res.audio_format


def test_probe_tries_next_syntax(session, tmp_path, monkeypatch):
    monkeypatch.setenv("EDEN_SIM_ACCEPT", "folder")
    res, settings = _probe(session, tmp_path)
    assert res.ok and settings.render_args == ["/R", "/Ewav", "/F{folder}"]
    assert any("aucun fichier WAV" in line for line in res.lines)


def test_probe_detects_unreliable_isolation(session, tmp_path, monkeypatch):
    monkeypatch.setenv("EDEN_SIM_IGNORE_MUTE", "1")
    res, settings = _probe(session, tmp_path)
    assert res.working_args and not res.ok
    assert settings.render_args is None  # nothing saved


def test_probe_without_any_output(session, tmp_path, monkeypatch):
    monkeypatch.setenv("EDEN_SIM_NO_OUTPUT", "1")
    res, settings = _probe(session, tmp_path)
    assert not res.working_args and settings.render_args is None


# -- verification ---------------------------------------------------------------

def test_null_test_format_mismatch(tmp_path):
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    sf.write(a, np.ones((100, 2)) * 0.1, 44100)
    sf.write(b, np.ones((100, 2)) * 0.1, 48000)
    assert "48000 Hz" in null_test(a, [b]).message


def test_cli_render_requires_probe(session, capsys):
    from eden.cli import main

    assert main(["render", str(session)]) == 2
    assert "fl-probe" in capsys.readouterr().err
