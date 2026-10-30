"""FL Studio renders fast without the PC lagging (render/plan.py, render/fl_studio.py).

The audio files of one Mixer track (same role) render together, as one voice; one launch of FL renders
every copy; a second FL renders beside it only on a PC with room for it; what does not work on this PC
(a folder render, two FL at once) is found out, kept, and the copies concerned are rendered alone.
"""

import json
import os
import threading
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from eden.mix.parts import split
from eden.render import fl_studio
from eden.render.fl_studio import FLStudioRenderer, RunOutcome, configured_renderer, side_by_side_count
from eden.render.pipeline import render_project
from eden.render.plan import plan_renders
from eden.settings import Settings, load_settings, save_settings
from flp_builder import Chan, Clip, Insert, Slot, build_flp
from test_render import BAR, _report, make_session, sim_renderer


def pc(monkeypatch, threads, free_gb=None):
    """The processor threads and the free memory of the PC FL Studio renders on, where FL is known to
    render the way Eden starts it (on Windows, on a desktop of its own)."""
    monkeypatch.setattr(fl_studio.os, "cpu_count", lambda: threads)
    monkeypatch.setattr(fl_studio, "_free_memory_gb", lambda: free_gb)
    monkeypatch.setattr(fl_studio, "_hidden_renders", True)


def traced(tmp_path, monkeypatch):
    trace = tmp_path / "trace.jsonl"
    monkeypatch.setenv("EDEN_SIM_TRACE", str(trace))
    return trace


def launches(trace):
    """What each launch of FL Studio rendered, in the order they ended."""
    return [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []


def copies_of(result):
    return len({j.copy_sha256 for j in result.jobs})


# -- the plan: one render per Mixer track ------------------------------------------------------------

def _voice(path, k, seconds=4.0):
    t = np.arange(int(seconds * 22050)) / 22050
    syllables = np.clip(np.sin(2 * np.pi * (3 + k) * t), 0, None)
    sf.write(path, 0.15 * np.random.default_rng(k).standard_normal(t.size) * syllables, 22050)


def track_session(tmp_path):
    """Three lead files and an adlib on the Mixer track « piste1 » (a compressor, then a bus with a
    reverb), two lead files played straight into the Master, and the beat."""
    d = tmp_path / "Piste"
    d.mkdir()
    names = ["Lead 1", "Lead 2", "Lead 3", "Adlib", "Lead 4", "Lead 5"]
    for k, name in enumerate(names):
        _voice(d / f"{name}.wav", k)
    t = np.arange(int(4.0 * 22050)) / 22050
    sf.write(d / "Beat.wav", np.stack([0.2 * np.sin(2 * np.pi * 55 * t)] * 2, axis=1), 22050)
    inserts = [Insert(routes=()),
               Insert(name="piste1", routes=(2,), slots={0: Slot("Fruity Compressor")}),
               Insert(name="Bus voix", routes=(0,), slots={0: Slot("Fruity Reeverb 2")})]
    channels = [Chan(name, insert=1 if k < 4 else 0, sample_path=str(d / f"{name}.wav"))
                for k, name in enumerate(names)]
    channels.append(Chan("Instru", insert=0, sample_path=str(d / "Beat.wav")))
    clips = [Clip(k + 1, (k % 3) * BAR // 2, BAR // 2, channel=k) for k in range(len(names))]
    clips.append(Clip(len(names) + 1, 0, BAR * 2, channel=len(names)))
    flp = d / "Piste.flp"
    flp.write_bytes(build_flp(channels, inserts, clips, tempo=120))
    return flp


def test_the_files_of_one_mixer_track_render_together(tmp_path):
    flp = track_session(tmp_path)
    report = _report(flp)
    roles = {s.label: s.role.role for s in report.sources}
    assert roles["Lead 1"] == roles["Lead 2"] == roles["Lead 3"] == roles["Lead 4"] != roles["Adlib"]
    plan = plan_renders(report)
    vocal = {j.name: j.channels for j in plan.jobs if j.kind == "vocal"}
    lead = roles["Lead 1"].replace("_", "-")
    # « piste1 »: its three lead files at once, its adlib apart (Eden does not mix them the same way); the leads
    # played straight into the Master: one voice too
    assert vocal == {f"vocal-ins001-{lead}": [0, 1, 2], "vocal-ch003-adlib": [3], f"vocal-master-{lead}": [4, 5]}
    descriptions = {j.name: j.description for j in plan.jobs}
    assert descriptions[f"vocal-ins001-{lead}"].startswith("piste1 (3 fichiers)")
    assert {j.name for j in plan.jobs if j.kind == "vocal_dry"} == {f"dry-ins001-{lead}", "dry-ch003-adlib"}
    assert {j.name: j.channels for j in plan.jobs if j.kind == "stem" and j.name.startswith("stem-master")} == {
        f"stem-master-{lead}": [4, 5]}

    result = render_project(flp, sim_renderer(), timeout_s=120, report=report)
    assert result.ok, (result.null_test, [j.error for j in result.jobs])
    # no Master effects: the song before the Master is the song; the Master voice alone is its stem
    assert copies_of(result) == len(plan.jobs) - 2
    parts = split(report, result)
    lead_label = next(s for s in report.sources if s.label == "Lead 4").role.label.capitalize()
    assert {tuple(v.channels): v.label for v in parts.voices} == {
        (0, 1, 2): "piste1 (3 fichiers)", (3,): "Adlib", (4, 5): f"{lead_label} (2 fichiers)"}
    together = next(v for v in parts.voices if v.channels == [0, 1, 2])
    assert together.dry is not None  # the reverb of « Bus voix » comes off: Eden works on the dry voice


# -- how many FL Studios ---------------------------------------------------------------------------

@pytest.mark.skipif(os.name != "nt", reason="Windows only")
def test_the_free_memory_of_the_pc_is_read():
    assert 0 < fl_studio._free_memory_gb() < 4096


def test_how_many_fl_studios_render_at_once(monkeypatch):
    for threads, free_gb, copies, expected in [(4, None, 9, 1), (2, None, 9, 1), (8, None, 9, 2),
                                               (32, None, 9, 2), (32, 3.0, 9, 1), (32, 64.0, 1, 1)]:
        pc(monkeypatch, threads, free_gb)
        assert side_by_side_count(copies) == expected, (threads, free_gb, copies)


def test_one_launch_of_fl_renders_every_copy(tmp_path, monkeypatch):
    pc(monkeypatch, threads=4)
    trace = traced(tmp_path, monkeypatch)
    session = make_session(tmp_path)
    renderer, learned = sim_renderer(), []
    renderer.on_learned = learned.append
    result = render_project(session, renderer, timeout_s=120)
    assert result.ok
    (run,) = launches(trace)
    assert len(run["projects"]) == copies_of(result) == 9
    assert renderer.folders is True and learned == [renderer]
    assert not (Path(result.folder) / "lots").exists()
    assert all(Path(j.wav_path).parent.name == j.job.name for j in result.jobs if j.status == "done")


def test_two_fl_studios_side_by_side_on_a_pc_with_room(tmp_path, monkeypatch):
    pc(monkeypatch, threads=8, free_gb=16.0)
    trace = traced(tmp_path, monkeypatch)
    renderer = sim_renderer()
    result = render_project(make_session(tmp_path), renderer, timeout_s=120)
    assert result.ok
    first, second = launches(trace)
    assert first["start"] < second["end"] and second["start"] < first["end"]  # at the same time
    assert len(first["projects"]) + len(second["projects"]) == copies_of(result)
    assert renderer.side_by_side is True and renderer.folders is True


def test_an_fl_that_will_not_start_beside_another_is_found_out(tmp_path, monkeypatch):
    pc(monkeypatch, threads=8)
    monkeypatch.setenv("EDEN_SIM_ALONE", str(tmp_path / "fl-ouvert"))
    trace = traced(tmp_path, monkeypatch)
    renderer = sim_renderer()
    result = render_project(make_session(tmp_path), renderer, timeout_s=120)
    assert result.ok and result.null_test.passed
    assert renderer.side_by_side is False and renderer.folders is True
    together, *alone = launches(trace)  # the copies of the one refused are rendered alone afterwards
    assert len(together["projects"]) > 1 and alone and all(len(r["projects"]) == 1 for r in alone)
    assert len(together["projects"]) + len(alone) == copies_of(result)

    trace.unlink()  # from now on, one FL: every copy in one launch
    other = tmp_path / "autre"
    other.mkdir()
    assert render_project(make_session(other), renderer, timeout_s=120).ok
    (run,) = launches(trace)
    assert len(run["projects"]) == 9


def test_where_fl_renders_no_folder_the_copies_go_one_by_one(tmp_path, monkeypatch):
    pc(monkeypatch, threads=4)
    monkeypatch.setenv("EDEN_SIM_ACCEPT", "project")
    started = []
    launch = FLStudioRenderer._launch

    def watched(self, args, folder, timeout_s, **kw):
        started.append(args[-1])
        return launch(self, args, folder, timeout_s, **kw)

    monkeypatch.setattr(FLStudioRenderer, "_launch", watched)
    renderer = sim_renderer()
    assert render_project(make_session(tmp_path), renderer, timeout_s=120).ok
    assert started[0].startswith("/F") and not any(a.startswith("/F") for a in started[1:])
    assert len(started) == 1 + 9 and renderer.folders is False

    started.clear()  # known now: not tried again
    other = tmp_path / "autre"
    other.mkdir()
    assert render_project(make_session(other), renderer, timeout_s=120).ok
    assert len(started) == 9 and not any(a.startswith("/F") for a in started)


# -- what FL left: rendered alone ----------------------------------------------------------------------

def _copies(tmp_path, names=("a", "b", "c")):
    copies = []
    for name in names:
        (tmp_path / name).mkdir()
        copy = tmp_path / name / f"{name}.flp"
        copy.write_bytes(b"FLhd")
        copies.append(copy)
    return copies


def test_the_last_wav_of_an_fl_closed_by_eden_is_rendered_again_alone(tmp_path, monkeypatch):
    pc(monkeypatch, threads=4)
    copies = _copies(tmp_path)

    def closed_while_rendering(self, args, folder, timeout_s, shown_if_nothing=True):
        for k, copy in enumerate(sorted(folder.glob("*.flp"))):
            wav = copy.with_suffix(".wav")
            wav.write_bytes(b"RIFF")
            os.utime(wav, (1000 + k, 1000 + k))
        return RunOutcome(None, False, 1.0, [], "", dialog="FL Studio — Plugin introuvable : Serum")

    monkeypatch.setattr(FLStudioRenderer, "_launch", closed_while_rendering)
    told = {}
    renderer = FLStudioRenderer(["FL64.exe"], ["/R", "/Ewav", "{project}"])
    renderer.render_many(copies, 60, lambda copy, wav: told.setdefault(copy.stem, wav.read_bytes()))
    assert sorted(told) == ["a", "b"]  # « c » was being written when FL was closed
    assert copies[2].read_bytes() == b"FLhd"  # back where it was, for ``render``
    assert not (tmp_path / "lots").exists() and renderer.folders is True


def test_each_wav_is_taken_as_soon_as_fl_is_done_with_it(tmp_path, monkeypatch):
    pc(monkeypatch, threads=4)
    monkeypatch.setattr(fl_studio, "WATCH_S", 0.05)
    copies = _copies(tmp_path)
    ended = threading.Event()

    def one_after_another(self, args, folder, timeout_s, shown_if_nothing=True):
        for copy in sorted(folder.glob("*.flp")):
            copy.with_suffix(".wav").write_bytes(b"RIFF")
            time.sleep(0.4)
        ended.set()
        return RunOutcome(0, False, 1.2, [], "")

    monkeypatch.setattr(FLStudioRenderer, "_launch", one_after_another)
    while_rendering = []
    FLStudioRenderer(["FL64.exe"], ["/R", "/Ewav", "{project}"]).render_many(
        copies, 60, lambda copy, wav: while_rendering.append((copy.stem, not ended.is_set())))
    assert while_rendering == [("a", True), ("b", True), ("c", False)]


def test_one_copy_at_a_time_is_left_to_render(tmp_path, monkeypatch):
    pc(monkeypatch, threads=4)
    monkeypatch.setattr(FLStudioRenderer, "_launch", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("lancé")))
    renderer = FLStudioRenderer(["FL64.exe"], ["/R", "/Ewav", "{project}"], folders=False)
    told = []
    renderer.render_many(_copies(tmp_path), 60, lambda copy, wav: told.append(copy))
    assert told == []  # nothing gained over ``render``: nothing launched


# -- what is learned is kept ---------------------------------------------------------------------------

def test_what_fl_does_on_this_pc_is_kept_in_the_settings(tmp_path, monkeypatch):
    exe = tmp_path / "FL64.exe"
    exe.write_bytes(b"MZ")
    settings_file = tmp_path / "settings.json"
    save_settings(Settings(fl_path=str(exe), render_args=["/R", "/Ewav", "{project}"]), settings_file)
    renderer = configured_renderer(settings_file)
    assert renderer.side_by_side is None and renderer.folders is None
    renderer.side_by_side, renderer.folders = False, True
    renderer.on_learned(renderer)
    kept = load_settings(settings_file)
    assert (kept.render_side_by_side, kept.render_folders) == (False, True)
    assert kept.render_args == ["/R", "/Ewav", "{project}"]
    again = configured_renderer(settings_file)
    assert (again.side_by_side, again.folders) == (False, True)


def test_folder_command_from_the_one_that_works():
    assert FLStudioRenderer(["FL64.exe"], ["/R", "/Ewav", "{project}"]).folder_args() == ["/R", "/Ewav", "/F{folder}"]
    assert FLStudioRenderer(["FL64.exe"], ["/R", "/Ewav", "/F{folder}"]).folder_args() == ["/R", "/Ewav", "/F{folder}"]
