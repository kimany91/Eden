import json
import os
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
from eden.render.verify import check_audio, null_test
from eden.settings import load_settings
from flp_builder import Chan, Clip, Insert, Slot, build_flp

SIM = str(Path(__file__).parent / "fl_simulator.py")
BAR = 96 * 4


def sim_renderer(args=("/R", "/Ewav", "{project}")):
    return FLStudioRenderer([sys.executable, SIM], list(args), name="simulateur")


class CapturingRenderer:
    """Keeps the bytes of every copy FL Studio is asked to render."""

    def __init__(self, inner):
        self.inner, self.copies, self.name = inner, {}, "capture"

    def render(self, copy, timeout_s):
        self.copies[copy.stem] = copy.read_bytes()
        return self.inner.render(copy, timeout_s)

    def at_once(self, copies):
        return self.inner.at_once(copies)

    def render_many(self, copies, timeout_s, on_rendered):
        self.copies.update((copy.stem, copy.read_bytes()) for copy in copies)
        self.inner.render_many(copies, timeout_s, on_rendered)


class CountingRenderer:
    """Counts the copies FL Studio renders."""

    def __init__(self, inner):
        self.inner, self.calls, self.name = inner, 0, "compteur"

    def render(self, copy, timeout_s):
        self.calls += 1
        return self.inner.render(copy, timeout_s)

    def at_once(self, copies):
        return self.inner.at_once(copies)

    def render_many(self, copies, timeout_s, on_rendered):
        def counted(copy, wav):
            self.calls += 1
            on_rendered(copy, wav)

        self.inner.render_many(copies, timeout_s, counted)


@pytest.fixture
def session(tmp_path):
    return make_session(tmp_path)


def make_session(tmp_path):
    """Lead + adlib into a vocal bus with reverb, an 808 also sent to that bus,
    a beat played straight into the Master, and a limiter on the Master."""
    d = tmp_path / "Session"
    d.mkdir(exist_ok=True)
    t = np.arange(int(4.0 * 22050)) / 22050
    rng = np.random.default_rng(7)
    for k, name in enumerate(("Lead.wav", "Adlib.wav", "Beat.wav", "808.wav")):
        if k < 2:  # voices: broadband and in syllables, so a delayed copy does not look like the voice
            syllables = np.clip(np.sin(2 * np.pi * (3 + k) * t), 0, None)
            sf.write(d / name, 0.15 * rng.standard_normal(t.size) * syllables, 22050)
        else:
            tone = 0.25 * np.sin(2 * np.pi * (140 + 90 * k) * t) * (0.6 + 0.4 * np.sin(2 * np.pi * (k + 1) * t))
            sf.write(d / name, np.stack([tone, 0.8 * tone], axis=1), 22050)
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
    ed.set_insert_effects_enabled(0, False)
    ed.set_channel_enabled(3, False)
    ed.set_sample_path(0, r"E:\Nouveau\Lead.wav")
    ed.set_route(5, 0, False)
    before, after = parse_bytes(original), parse_bytes(ed.to_bytes())
    assert after.insert(0).effects_enabled is False and before.insert(0).effects_enabled is True
    assert after.channel(3).enabled is False
    assert after.channel(0).sample_path == r"E:\Nouveau\Lead.wav"
    assert [r.target for r in after.insert(5).routes] == [3]
    for idx in (1, 2, 3, 4):
        assert after.insert(idx) == before.insert(idx)
    assert [c.name for c in after.channels] == [c.name for c in before.channels]
    assert len(ed.changes) == 4
    assert session.read_bytes() == original  # the file on disk is untouched


def test_editor_on_real_project(real_flp):
    ed = FlpEditor(real_flp.read_bytes())
    ed.set_insert_effects_enabled(19, False)
    ed.set_channel_enabled(11, False)
    p = parse_bytes(ed.to_bytes())
    assert p.insert(19).effects_enabled is False and p.insert(19).name == "Plugin Test"
    assert p.channel(11).enabled is False and p.channel(11).name == "22in Kick"


def test_editor_errors(session):
    ed = FlpEditor(session.read_bytes())
    with pytest.raises(FlpEditError):
        ed.set_insert_effects_enabled(500, False)
    with pytest.raises(FlpEditError):
        ed.set_channel_enabled(42, False)


# -- plan ---------------------------------------------------------------------------

def test_render_plan(session):
    plan = plan_renders(_report(session))
    kinds = [j.kind for j in plan.jobs]
    assert kinds[:2] == ["original", "premaster"]
    stems = {j.name: j for j in plan.jobs if j.kind == "stem"}
    assert set(stems) == {"stem-003-bus-voix", "stem-005-808", "stem-ch002-instru"}
    bus, the_808 = stems["stem-003-bus-voix"], stems["stem-005-808"]
    # the bus plays everything feeding it, the 808's send included: only the beat (straight into the Master) is
    # muted, and the 808's direct route to the Master is cut; no Mixer track is ever switched off
    assert bus.mute_channels == [2] and bus.cut_routes == [(5, 0)]
    assert the_808.mute_channels == [0, 1, 2] and the_808.cut_routes == [(5, 3)]  # 808 stem: its send to the bus cut
    assert stems["stem-ch002-instru"].mute_channels == [0, 1, 3]
    # the Master's limiter is bypassed as an effect of its own (FL recorded its state), not by the Master's switch
    assert all((0, 0) in j.bypass_slots and not j.bypass_master_switch for j in plan.jobs[1:])
    assert plan.jobs[0].bypass_slots == [] and not plan.jobs[0].mute_channels
    vocal = {j.name for j in plan.jobs if j.kind == "vocal"}
    assert vocal == {"vocal-ch000-lead", "vocal-ch001-adlib"}
    dry = {j.name: j for j in plan.jobs if j.kind == "vocal_dry"}
    assert set(dry) == {"dry-ch000-lead", "dry-ch001-adlib"}
    # the vocal bus carries the reverb and the voices need it to reach the Master:
    # its reverb slot is bypassed, the bus itself stays
    assert dry["dry-ch000-lead"].bypass_slots == [(3, 0), (0, 0)] and not dry["dry-ch000-lead"].cut_routes
    assert any("plusieurs groupes" in n for n in plan.notes)


def make_send_session(tmp_path):
    """Lead with Auto-Tune and a delay on its own insert, plus a send to a reverb return."""
    d = tmp_path / "Sends"
    d.mkdir(exist_ok=True)
    t = np.arange(int(2.0 * 22050)) / 22050
    sf.write(d / "Lead.wav", 0.3 * np.sin(2 * np.pi * 220 * t), 22050)
    sf.write(d / "Beat.wav", np.stack([0.2 * np.sin(2 * np.pi * 55 * t)] * 2, axis=1), 22050)
    inserts = [
        Insert(routes=()),
        Insert(name="Lead", routes=(0, 2), slots={0: Slot("Auto-Tune Pro"), 1: Slot("Fruity Delay 3")}),
        Insert(name="Reverb", routes=(0,), slots={0: Slot("Fruity parametric EQ 2"),
                                                 1: Slot("Fruity Reeverb 2")}),
        Insert(name="Beat", routes=(0,), slots={0: Slot("Fruity Reeverb 2")}),
    ]
    channels = [Chan("Lead", insert=1, sample_path=str(d / "Lead.wav")),
                Chan("Instru", insert=3, sample_path=str(d / "Beat.wav"))]
    clips = [Clip(1, 0, BAR, channel=0), Clip(2, 0, BAR, channel=1)]
    flp = d / "Sends.flp"
    flp.write_bytes(build_flp(channels, inserts, clips, tempo=120))
    return flp


def test_dry_vocal_plan_silences_returns_and_bypasses_space_slots(tmp_path):
    plan = plan_renders(_report(make_send_session(tmp_path)))
    dry = next(j for j in plan.jobs if j.kind == "vocal_dry")
    assert dry.cut_routes == [(2, 0)]  # reverb return: nothing of it reaches the Master; the lead does without it
    assert dry.bypass_slots == [(1, 1)]  # delay on the lead's own insert; Auto-Tune stays
    assert dry.mute_channels == [1] and dry.channels == [0]


def test_dry_edits_mute_a_whole_return_and_need_every_slot_state():
    from eden.project.classify import RoleGuess
    from eden.project.inspector import SourceAnalysis, _effects_on, _signal_path
    from eden.project.model import FlpProject, MixerInsert, MixerSlot, PluginInfo, Route
    from eden.render.plan import _dry_edits

    def lead(project):
        path, reaches = _signal_path(project, 1)
        return SourceAnalysis(1, "Lead", "sampler", 1, "Lead", path, reaches,
                              _effects_on(project, [i for i in path if i]), RoleGuess("lead_vocal"), 1, 0.0, 10.0)

    tune = MixerSlot(0, PluginInfo("Fruity Wrapper", vst_name="Auto-Tune Pro"), enabled=True)
    # a reverb return ducked by a limiter: the limiter only shapes the effect, the whole return is muted
    ducked = FlpProject(inserts=[
        MixerInsert(0, "Master", routes=[]),
        MixerInsert(1, "Lead", slots=[tune], routes=[Route(0), Route(2, 6400)]),
        MixerInsert(2, "Rev", routes=[Route(0)], slots=[MixerSlot(0, PluginInfo("Fruity Reeverb 2"), enabled=True),
                                                        MixerSlot(1, PluginInfo("Fruity Limiter"), enabled=True)])])
    assert _dry_edits(ducked, lead(ducked)) == ([2], [], None)
    # a reverb whose on/off state FL did not store cannot be bypassed: no dry render is trusted
    unknown = FlpProject(inserts=[
        MixerInsert(0, "Master", routes=[]),
        MixerInsert(1, "Lead", routes=[Route(0)], slots=[
            tune, MixerSlot(1, PluginInfo("Fruity Reeverb 2"), enabled=None),
            MixerSlot(2, PluginInfo("Fruity Delay 3"), enabled=True)])])
    returns, slots, left_in = _dry_edits(unknown, lead(unknown))
    assert (returns, slots) == ([], [(1, 2)]) and "« Fruity Reeverb 2 »" in left_in


def test_editor_bypasses_one_slot(tmp_path):
    data = make_send_session(tmp_path).read_bytes()
    ed = FlpEditor(data)
    ed.set_slot_enabled(1, 1, False)
    p = parse_bytes(ed.to_bytes())
    assert [s.enabled for s in p.insert(1).slots] == [True, False]
    assert p.insert(2).slots[1].enabled is True
    with pytest.raises(FlpEditError):
        ed.set_slot_enabled(1, 7, False)


def test_dry_vocal_render_removes_only_the_fl_space_effects(tmp_path):
    result = render_project(make_send_session(tmp_path), sim_renderer(), timeout_s=120)
    assert result.ok
    full = sf.read(result.wav("vocal-ch000-lead"))[0]
    dry = sf.read(result.wav("dry-ch000-lead"))[0]
    sr = 22050
    after = slice(int(2.05 * sr), int(2.7 * sr))  # after the clip: echoes and reverb only
    assert np.max(np.abs(dry[after])) < 1e-6 < np.max(np.abs(full[after]))
    # while the voice sounds, the dry render is the voice through Auto-Tune alone
    t = np.arange(int(2.0 * sr)) / sr
    expected = np.tanh(1.5 * 0.3 * np.sin(2 * np.pi * 220 * t) * 10000 / 12800) / 1.5
    np.testing.assert_allclose(dry[: int(0.2 * sr), 0], expected[: int(0.2 * sr)], atol=1e-4)  # 16-bit source


# -- full pipeline ---------------------------------------------------------------

def test_render_pipeline_reproduces_the_mix(session, tmp_path):
    original = session.read_bytes()
    renderer = CountingRenderer(sim_renderer())
    result = render_project(session, renderer, timeout_s=120, workspace_home=None)
    assert result.ok, (result.null_test, [j.error for j in result.jobs])
    assert result.null_test.residual_db < -100
    assert renderer.calls == len(result.plan.jobs) == 9
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
    assert "il est surtout entre 0:" in result.null_test.message  # where the missing 808 is, to find it


def _wav(path, data, sr=1000):
    sf.write(path, data, sr, subtype="FLOAT")
    return path


def test_a_failed_null_test_says_what_the_gap_is_like(tmp_path):
    sr = 1000
    t = np.arange(5 * sr) / sr
    a = np.stack([0.3 * np.sin(2 * np.pi * 50 * t)] * 2, axis=1)
    b = np.zeros_like(a)
    b[2 * sr:3 * sr] = 0.3 * np.sin(2 * np.pi * 130 * t[2 * sr:3 * sr])[:, None]
    song = _wav(tmp_path / "song.wav", a + b)
    half = _wav(tmp_path / "b-half.wav", b / 2)
    gap = null_test(song, [_wav(tmp_path / "a.wav", a), half])
    assert not gap.passed and gap.resembles == str(half) and not gap.resembles_mix and gap.loudest == (2.0, 3.0)
    quieter = null_test(song, [_wav(tmp_path / "a-half.wav", a / 2), half])
    assert quieter.resembles_mix  # every part at half its level


def test_a_16_bit_render_at_full_scale_is_clipped(tmp_path):
    path = tmp_path / "16.wav"
    sf.write(path, np.full((100, 2), 1.5), 44100, subtype="PCM_16")  # +32767 at most
    assert check_audio(path).clipped_samples == 200


def test_moved_samples_are_repaired_in_copies(session, tmp_path):
    moved = tmp_path / "Ailleurs"
    session.parent.rename(moved)
    project = moved / "Session.flp"
    renderer = CapturingRenderer(sim_renderer())
    result = render_project(project, renderer, timeout_s=120)
    assert result.repairs and result.ok
    copy = parse_bytes(renderer.copies["original"])
    assert Path(copy.channel(0).sample_path).parent == moved


def test_copies_are_deleted_after_rendering(session):
    result = render_project(session, sim_renderer(), timeout_s=120)
    workspace = Path(result.folder).parent.parent
    assert not list(workspace.rglob("*.flp"))  # only audio and the manifest remain
    assert not list(Path(result.folder).rglob("*entree.wav"))
    assert {p.suffix for p in Path(result.folder).rglob("*.*")} == {".wav", ".json"}


def test_copy_is_deleted_even_when_fl_fails(session, monkeypatch):
    monkeypatch.setenv("EDEN_SIM_NO_OUTPUT", "1")
    with pytest.raises(RenderError):
        render_project(session, sim_renderer(), timeout_s=120)
    assert not list(Path(os.environ["EDEN_HOME"]).rglob("*.flp"))


def test_echo_tail_cut_by_fl_is_reported(session, monkeypatch):
    monkeypatch.setenv("EDEN_SIM_CUT_TAIL", "1")
    result = render_project(session, sim_renderer(), timeout_s=120)
    assert any("Leave remainder" in w for w in result.warnings)


def test_no_tail_warning_when_effects_ring_out(session):
    result = render_project(session, sim_renderer(), timeout_s=120)
    assert not any("Leave remainder" in w for w in result.warnings)
    assert not any(j.check.ends_with_sound for j in result.jobs)


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
    assert res.ok and len(res.lines) == 4  # FL Studio, one try, its render, settings saved: nothing else rendered
    assert not list(Path(os.environ["EDEN_HOME"]).rglob("probe/*"))  # test copies and renders removed
    assert settings.render_args == ["/R", "/Ewav", "{project}"]
    assert "FLOAT" in res.audio_format


def test_probe_tries_next_syntax(session, tmp_path, monkeypatch):
    monkeypatch.setenv("EDEN_SIM_ACCEPT", "folder")
    res, settings = _probe(session, tmp_path)
    assert res.ok and settings.render_args == ["/R", "/Ewav", "/F{folder}"]
    assert any("aucun fichier WAV" in line for line in res.lines)


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


# -- copies FL Studio 2025/2026 renders, as few as possible ------------------------------------------

def test_no_copy_switches_a_mixer_track_off(session):
    # FL Studio 2025/2026 closes without a file on a copy where one is off: parts are played alone by muting
    # channels and cutting sends only
    from eden.render.pipeline import build_copy

    report = _report(session)
    original = session.read_bytes()
    before = parse_bytes(original)
    for job in plan_renders(report).jobs:
        copy = parse_bytes(build_copy(original, job, {}))
        assert [i.enabled for i in copy.inserts] == [i.enabled for i in before.inserts], job.name


def test_identical_copies_cost_one_render(tmp_path, monkeypatch):
    # a voice played straight into the Master is the same copy as that voice alone; without Master effects the
    # song before the Master is the song itself
    d = tmp_path / "Direct"
    d.mkdir()
    t = np.arange(int(2.0 * 22050)) / 22050
    sf.write(d / "Lead.wav", 0.2 * np.sin(2 * np.pi * 220 * t), 22050)
    sf.write(d / "Beat.wav", np.stack([0.2 * np.sin(2 * np.pi * 55 * t)] * 2, axis=1), 22050)
    flp = d / "Direct.flp"
    flp.write_bytes(build_flp([Chan("Lead", insert=0, sample_path=str(d / "Lead.wav")),
                               Chan("Instru", insert=0, sample_path=str(d / "Beat.wav"))],
                              [Insert(routes=())], [Clip(1, 0, BAR, channel=0), Clip(2, 0, BAR, channel=1)],
                              tempo=120))
    trace = tmp_path / "trace.jsonl"
    monkeypatch.setenv("EDEN_SIM_TRACE", str(trace))
    result = render_project(flp, sim_renderer(), timeout_s=120, report=_report(flp))
    assert result.ok and len(result.jobs) == 5
    rendered = [name for line in trace.read_text().splitlines() for name in json.loads(line)["projects"]]
    assert sorted(rendered) == ["original", "stem-ch000-lead", "stem-ch001-instru"]
    assert {j.job.name: j.status for j in result.jobs if j.status == "resumed"} == {
        "premaster": "resumed", "vocal-ch000-lead": "resumed"}
