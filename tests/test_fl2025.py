"""Projects saved by FL Studio 2024 and later: their playlist is read (80-byte clips since FL 2024, 88 in
FL 26), and the channels of the Channel Rack that play nowhere in the song (a template's drums whose
samples are gone) no longer stop Eden over a missing file."""

import numpy as np
import pytest
import soundfile as sf

from eden.flp.parser import parse_bytes
from eden.gui import viewmodel
from eden.project.inspector import inspect_project
from eden.project.sources import SearchRoots
from eden.render.fl_studio import RenderError
from eden.render.pipeline import sample_repairs
from flp_builder import Chan, Clip, Insert, build_flp
from test_render import BAR

FL25 = "25.1.6.4997"


@pytest.mark.parametrize("version, size", [("20.8.4.2576", 32), ("21.2.3.4004", 60), ("24.1.2.4430", 80),
                                           (FL25, 80), ("26.1.1.5000", 88)])
def test_the_playlist_of_each_fl_version_is_read(version, size):
    clips = [Clip(1, 0, BAR * 4, channel=0), Clip(3, BAR * 2, BAR * 8, channel=1)]
    p = parse_bytes(build_flp([Chan("Voix"), Chan("Instru")], [Insert(routes=())], clips, version=version,
                              item_size=size))
    got = [(c.track, c.position_ticks, c.length_ticks, c.source_index) for c in p.arrangements[0].clips]
    assert got == [(1, 0, BAR * 4, 0), (3, BAR * 2, BAR * 8, 1)] and not p.warnings


def test_a_length_two_sizes_share_is_read_with_the_size_the_version_writes():
    clips = [Clip(t, BAR * t, BAR, channel=t - 1) for t in (1, 2, 3)]  # 3 × 80 = 240 = 4 × 60 bytes
    p = parse_bytes(build_flp([Chan(f"c{i}") for i in range(3)], [Insert(routes=())], clips, version=FL25,
                              item_size=80))
    assert [(c.track, c.source_index) for c in p.arrangements[0].clips] == [(1, 0), (2, 1), (3, 2)]


def _song(tmp_path, template_clip: bool = False):
    """Voices recorded over a downloaded beat in a project started from a template whose drums' samples
    are gone; the takes are named by FL, the playlist tracks by the rapper."""
    folder = tmp_path / "Vertige"
    folder.mkdir()
    t = np.arange(int(40.0 * 22050)) / 22050
    rng = np.random.default_rng(1)
    take = 0.2 * rng.standard_normal(t.size) * np.clip(np.sin(2 * np.pi * 3 * t), 0, None)
    sf.write(folder / "Vertige_take_01.wav", take, 22050)
    sf.write(folder / "Vertige_take_02.wav", 0.5 * take, 22050)
    beat = "lucki type beat - 'casino' [D# min, 149 BPM]"
    sf.write(folder / f"{beat}.wav", np.stack([take, take], 1), 22050)
    template = r"C:\Users\Kimany\Documents\FL STUDIO MODEL\MODEL FL\Samples"
    channels = [Chan("808 Kick", sample_path=template + r"\Basic 808 Kick.wav"),
                Chan("808 Clap", sample_path=template + r"\Basic 808 Clap.wav"),
                Chan("FLEX Bass", plugin="FLEX"),
                Chan(beat, sample_path=str(folder / f"{beat}.wav")),
                Chan("Vertige_take_01", insert=1, sample_path=str(folder / "Vertige_take_01.wav")),
                Chan("Vertige_take_02", insert=2, sample_path=str(folder / "Vertige_take_02.wav"))]
    inserts = [Insert(routes=()), Insert(name="Insert 1", routes=(0,)), Insert(name="Insert 2", routes=(0,))]
    clips = [Clip(1, 0, BAR * 20, channel=3), Clip(2, 0, BAR * 20, channel=4), Clip(3, 0, BAR * 10, channel=5)]
    if template_clip:
        clips.append(Clip(4, 0, BAR, channel=0))
    flp = folder / "Vertige.flp"
    flp.write_bytes(build_flp(channels, inserts, clips, track_names={1: "Prod", 2: "Lead", 3: "Backs"}, tempo=120,
                              version=FL25, item_size=80))
    return inspect_project(flp, roots=SearchRoots(), archive_report=False)


def test_channels_that_play_nowhere_do_not_stop_eden(tmp_path):
    report = _song(tmp_path)
    assert report.project_end_seconds == pytest.approx(40.0)
    assert sorted(report.idle_channels) == ["808 Clap", "808 Kick", "FLEX Bass"]
    assert [s.label for s in report.sources] == ["lucki type beat - 'casino' [D# min, 149 BPM]",
                                                 "Vertige_take_01", "Vertige_take_02"]
    sample_repairs(report)  # the template's missing samples change nothing: no error
    # the playlist's track names tell the voices apart
    assert [s.role.role for s in report.vocal_sources] == ["lead_vocal", "back_vocal"]
    lines = viewmodel.analysis_lines(viewmodel.report_view(report))
    assert any(text.startswith("3 canal(aux) du Channel Rack ne joue(nt) nulle part") for text, _ in lines)


def test_a_missing_file_that_plays_still_stops_eden(tmp_path):
    report = _song(tmp_path, template_clip=True)  # "808 Kick" plays once in the playlist
    assert "808 Kick" not in report.idle_channels
    with pytest.raises(RenderError, match="808 Kick"):
        sample_repairs(report)
