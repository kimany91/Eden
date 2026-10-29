"""Checks against a real project saved by FL Studio 20.8.4 (PyFLP test asset).

Expected values were cross-checked with PyFLP 2.2.1 running on Python 3.10.
"""

from eden.flp.parser import parse_bytes
from eden.project.inspector import inspect_project
from eden.project.sources import SearchRoots


def test_real_project(real_flp):
    p = parse_bytes(real_flp.read_bytes())
    assert p.fl_version == "20.8.4.2576"
    assert p.tempo_bpm == 69.42
    assert (p.title, p.artists, p.genre) == ("PyFLP Test FLP", "demberto", "Testing...")
    assert len(p.channels) == 19 == p.header_channel_count
    names = [c.name for c in p.channels]
    assert names[:3] == ["BooBass", "Instrument track", "Layer"]
    assert p.channel(1).insert == 2
    assert p.channel(12).volume_raw == 0 and p.channel(14).pan_raw == 0
    assert p.channel(16).enabled is False and p.channel(17).locked is True
    vst = p.channel(6).plugin
    assert (vst.format, vst.vst_name, vst.vendor) == ("vst2", "Sylenth1", "LennarDigital")

    assert len(p.inserts) == 127
    assert p.insert(1).name == "Audio track"
    assert p.insert(4).volume_raw == 0
    assert (p.insert(6).pan_raw, p.insert(7).pan_raw) == (-6400, 6400)
    assert p.insert(10).enabled is False
    assert p.insert(18).effects_enabled is False
    assert [r.target for r in p.insert(5).routes] == []
    plugin_test = [s.plugin.label for s in p.insert(19).slots]
    assert plugin_test[:2] == ["Fruity Balance", "Fruity Fast Dist"]
    assert p.insert(19).slots[-1].plugin.vst_name == "OTT"
    assert p.insert(19).slots[-1].plugin.format == "vst3"

    arr = p.arrangements[0]
    assert arr.name == "Just tracks"
    assert len(arr.clips) == 22
    audio_track = next(t for t in arr.tracks if t.name == "Audio track")
    assert {c.source_index for c in arr.clips if c.track == audio_track.number} == {11}
    disabled = next(t for t in arr.tracks if t.name == "Disabled")
    assert disabled.enabled is False
    assert [m.name for m in p.arrangements[1].markers][1:4] == ["2/8", "4/4", "3rd bar"]


def test_real_project_inspection(real_flp):
    r = inspect_project(real_flp, roots=SearchRoots())
    kick = next(s for s in r.sources if s.label == "22in Kick")
    assert kick.role.role == "drums"
    assert kick.sample.is_factory
    assert "Iconified" not in {s.label for s in r.sources}  # MIDI Out makes no sound
