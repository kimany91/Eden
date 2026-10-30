"""FL Studio renders fast without the PC lagging (render/plan.py, render/fl_studio.py).

The audio files of one Mixer track (same role) render together, as one voice; as many FL Studios render
side by side as the PC has processor threads and free memory for; an FL that will not start beside
another is found out, kept, and the copies concerned are rendered alone; an FL that stays open once its
WAV is written is closed.
"""

import json
import os
import sys
import textwrap
import time

import numpy as np
import pytest
import soundfile as sf

from eden.mix.parts import split
from eden.render import fl_studio
from eden.render.fl_studio import FLStudioRenderer, RenderError, configured_renderer, side_by_side_count
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
    # in the sum, the voices played straight into the Master are one stem: they may share effects Eden cannot see
    assert {j.name: j.channels for j in plan.jobs if j.kind == "stem" and j.name.startswith("stem-master")} == {
        "stem-master-voix": [4, 5]}

    result = render_project(flp, sim_renderer(), timeout_s=120, report=report)
    assert result.ok, (result.null_test, [j.error for j in result.jobs])
    # no Master effects: the song before the Master is the song; the Master voices together are their stem
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


def test_as_many_fl_studios_as_the_pc_has_room_for(monkeypatch):
    for threads, free_gb, copies, expected in [(2, None, 9, 1), (4, None, 9, 2), (8, None, 9, 4), (32, None, 9, 8),
                                               (32, 3.0, 9, 1), (32, 8.0, 9, 4), (32, 64.0, 3, 3)]:
        pc(monkeypatch, threads, free_gb)
        assert side_by_side_count(copies) == expected, (threads, free_gb, copies)


def _overlap(runs):
    return any(a["start"] < b["end"] and b["start"] < a["end"] for i, a in enumerate(runs) for b in runs[i + 1:])


def test_several_fl_studios_render_side_by_side(tmp_path, monkeypatch):
    pc(monkeypatch, threads=8, free_gb=16.0)
    trace = traced(tmp_path, monkeypatch)
    renderer, learned = sim_renderer(), []
    renderer.on_learned = learned.append
    result = render_project(make_session(tmp_path), renderer, timeout_s=120)
    assert result.ok
    runs = launches(trace)
    assert len(runs) == copies_of(result) == 9 and all(len(r["projects"]) == 1 for r in runs)
    assert _overlap(runs)  # at the same time
    assert renderer.side_by_side is True and learned == [renderer]


def test_an_fl_that_will_not_start_beside_another_is_found_out(tmp_path, monkeypatch):
    pc(monkeypatch, threads=8)
    monkeypatch.setenv("EDEN_SIM_ALONE", str(tmp_path / "fl-ouvert"))
    trace = traced(tmp_path, monkeypatch)
    renderer = sim_renderer()
    result = render_project(make_session(tmp_path), renderer, timeout_s=120)
    assert result.ok and result.null_test.passed  # the copies of the ones refused are rendered alone afterwards
    assert renderer.side_by_side is False and len(launches(trace)) == copies_of(result)

    trace.unlink()  # from now on, one FL at a time
    other = tmp_path / "autre"
    other.mkdir()
    assert render_project(make_session(other), renderer, timeout_s=120).ok
    runs = launches(trace)
    assert len(runs) == 9 and not _overlap(runs)


def test_one_copy_at_a_time_is_left_to_render(tmp_path, monkeypatch):
    pc(monkeypatch, threads=2)
    monkeypatch.setattr(FLStudioRenderer, "run", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("lancé")))
    told = []
    copies = []
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
        copies.append(tmp_path / name / f"{name}.flp")
    sim_renderer().render_many(copies, 60, lambda copy, wav: told.append(copy))
    assert told == []  # nothing gained over ``render``: nothing launched


# -- an FL that stays open ----------------------------------------------------------------------------

def _fl(tmp_path, body):
    """A stand-in for FL Studio: ``python fl.py /R /Ewav <copy>``."""
    script = tmp_path / "fl.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return FLStudioRenderer([sys.executable, str(script)], ["/R", "/Ewav", "{project}"])


def _copy(tmp_path):
    (tmp_path / "rendu").mkdir()
    copy = tmp_path / "rendu" / "copie.flp"
    copy.write_bytes(b"FLhd")
    return copy


def test_an_fl_that_stays_open_once_its_wav_is_written_is_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(fl_studio, "DONE_GRACE_S", 0.5)
    renderer = _fl(tmp_path, """
        import sys, time
        from pathlib import Path
        import numpy as np, soundfile as sf
        sf.write(Path(sys.argv[-1]).with_suffix(".wav"), np.zeros((2205, 2)), 22050, subtype="FLOAT")
        time.sleep(120)  # FL left open once its file is written
    """)
    copy = _copy(tmp_path)
    start = time.monotonic()
    wav = renderer.render(copy, timeout_s=100)
    assert wav == copy.with_suffix(".wav") and time.monotonic() - start < 30
    assert sf.info(str(wav)).frames == 2205


def test_a_wav_still_being_written_or_left_by_an_earlier_render_is_not_done(tmp_path, monkeypatch):
    monkeypatch.setattr(fl_studio, "DONE_GRACE_S", 0.2)
    copy = _copy(tmp_path)
    sf.write(copy.with_suffix(".wav"), np.zeros((100, 2)), 22050)  # an earlier render's
    renderer = _fl(tmp_path, """
        import sys, time
        from pathlib import Path
        wav = Path(sys.argv[-1]).with_suffix(".wav")
        time.sleep(1.0)
        wav.write_bytes(b"RIFF\\x00\\x00\\x00\\x00WAVEfmt ")  # its header not filled in yet: still being written
        time.sleep(120)
    """)
    with pytest.raises(RenderError, match="pas terminé"):
        renderer.render(copy, timeout_s=3)
    assert fl_studio._written(copy.with_suffix(".wav")) is None
    sf.write(copy.with_suffix(".wav"), np.zeros((100, 2)), 22050)
    assert fl_studio._written(copy.with_suffix(".wav")) == copy.with_suffix(".wav").stat().st_size


# -- what is learned is kept ---------------------------------------------------------------------------

def test_whether_fl_studios_render_side_by_side_is_kept_in_the_settings(tmp_path):
    exe = tmp_path / "FL64.exe"
    exe.write_bytes(b"MZ")
    settings_file = tmp_path / "settings.json"
    save_settings(Settings(fl_path=str(exe), render_args=["/R", "/Ewav", "{project}"]), settings_file)
    renderer = configured_renderer(settings_file)
    assert renderer.side_by_side is None
    renderer.side_by_side = False
    renderer.on_learned(renderer)
    kept = load_settings(settings_file)
    assert kept.render_side_by_side is False and kept.render_args == ["/R", "/Ewav", "{project}"]
    assert configured_renderer(settings_file).side_by_side is False
