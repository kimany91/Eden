"""The before / after player (gui/player.py): one playhead for both versions, switches and seeks
without a click, "même volume" lowering the louder version, and the Qt side pulling it as it plays."""

import os

import numpy as np
import pytest
import soundfile as sf

from eden.gui.player import FADE_S, Comparison, load_comparison

FS = 48000


def _tones(seconds=2.0):
    t = np.arange(int(seconds * FS)) / FS
    before = 0.25 * np.sin(2 * np.pi * 220 * t)
    after = 0.5 * np.sin(2 * np.pi * 330 * t)
    return np.stack([before, before], 1), np.stack([after, after], 1)


def _play(c: Comparison, frames: int, block: int = 512) -> np.ndarray:
    out = [c.read(min(block, frames - done)) for done in range(0, frames, block)]
    return np.concatenate(out)


def test_both_versions_share_one_playhead_and_switch_without_a_click():
    before, after = _tones()
    c = Comparison(before, after, FS, (-12.0, -9.0))
    c.matched = False
    c.play()
    first = _play(c, 24000)
    assert c.position == 24000 and c.source == "after"
    c.switch("before")
    second = _play(c, 24000)
    assert c.position == 48000  # the same moment, in the other version
    # after the 10 ms crossfade it is the original, exactly where the playhead is
    fade = int(FADE_S * FS)
    assert np.allclose(second[fade:, 0], before[24000 + fade:48000, 0], atol=1e-6)
    # no click: no step between samples larger than the signals' own
    joined = np.concatenate([first, second])[:, 0]
    assert np.abs(np.diff(joined)).max() < 1.05 * max(np.abs(np.diff(before[:, 0])).max(),
                                                      np.abs(np.diff(after[:, 0])).max())


def test_same_volume_lowers_the_louder_version_to_the_other():
    before, after = _tones()
    c = Comparison(before, after, FS, (-12.0, -9.0))
    assert c.matched and c.match_db() == pytest.approx(3.0)
    assert c.gain("after") == pytest.approx(10 ** (-3 / 20)) and c.gain("before") == 1.0
    c.set_matched(False)
    assert c.gain("after") == 1.0
    # without both measures nothing is changed
    assert Comparison(before, after, FS).gain("after") == 1.0


def test_starting_pausing_and_seeking_are_faded():
    before, after = _tones()
    c = Comparison(before, after, FS, (-12.0, -9.0))
    assert not c.read(256).any()  # not playing: silence
    c.play()
    start = c.read(1024)
    fade = int(FADE_S * FS)
    assert abs(start[0, 0]) < 0.01 and np.allclose(np.abs(start[fade:, 0]).max(), 0.5 * c.gain("after"), atol=0.01)
    c.seek(FS)  # one second later, faded across
    assert c.position == FS
    c.read(4096)
    c.pause()
    tail = c.read(1024)
    assert np.abs(tail[fade:]).max() == 0 and not c.playing
    position = c.position
    assert not c.read(512).any() and c.position == position  # paused: the playhead waits


def test_the_end_of_the_song_stops_it():
    before, after = _tones(0.1)
    c = Comparison(before, after, FS)
    c.play()
    _play(c, 6144)
    assert c.ended and c.position == c.frames
    c.play()  # played again: from the start
    assert c.position == 0 and not c.ended


def test_a_mix_without_its_original_plays_alone_and_lengths_are_matched():
    before, after = _tones(1.0)
    c = Comparison(None, after, FS)
    assert not c.has_before
    c.switch("before")
    assert c.source == "after"
    longer = Comparison(np.concatenate([before, before]), after, FS)
    assert longer.frames == 2 * len(before) and len(longer.tracks["after"]) == longer.frames


def test_files_are_read_at_the_outputs_rate(tmp_path):
    before, after = _tones(0.5)
    sf.write(tmp_path / "original.wav", before, FS, subtype="FLOAT")
    sf.write(tmp_path / "final.wav", after, FS, subtype="FLOAT")
    c = load_comparison(str(tmp_path / "original.wav"), str(tmp_path / "final.wav"), (-12.0, -9.0))
    assert c.fs == FS and c.has_before and c.frames == len(after)
    resampled = load_comparison(str(tmp_path / "original.wav"), str(tmp_path / "final.wav"), (-12.0, -9.0),
                                rate=44100)
    assert resampled.fs == 44100 and abs(resampled.frames - len(after) * 44100 / FS) <= 1
    missing = load_comparison(str(tmp_path / "absent.wav"), str(tmp_path / "final.wav"), (None, None))
    assert not missing.has_before


# -- the Qt side, with a stand-in for the sound card ------------------------------------------------

@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtGui = pytest.importorskip("PySide6.QtGui")
    return QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])


class _Sink:
    def __init__(self):
        self.device, self.state = None, "idle"

    def start(self, device):
        self.device, self.state = device, "active"

    def suspend(self):
        self.state = "suspended"

    def resume(self):
        self.state = "active"

    def stop(self):
        self.state = "stopped"

    def bufferSize(self):
        return 8192

    def bytesFree(self):
        return 8192

    def deleteLater(self):
        pass


class _Output:
    available = True

    def __init__(self):
        self.sinks = []

    def format(self, fs):
        from PySide6.QtMultimedia import QAudioFormat

        fmt = QAudioFormat()
        fmt.setChannelCount(2)
        fmt.setSampleRate(fs)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
        return fmt

    def sink(self, fmt, parent):
        self.sinks.append(_Sink())
        return self.sinks[-1]


def _wait(condition, ms=10000):
    from PySide6.QtCore import QEventLoop, QTimer

    waited = 0
    while not condition() and waited < ms:
        loop = QEventLoop()
        QTimer.singleShot(20, loop.quit)
        loop.exec()
        waited += 20
    assert condition()


def test_the_player_loads_a_version_and_the_output_pulls_it(app, tmp_path):
    from eden.gui.player import ABPlayer

    before, after = _tones(1.0)
    sf.write(tmp_path / "original.wav", before, FS, subtype="FLOAT")
    sf.write(tmp_path / "final.wav", after, FS, subtype="FLOAT")
    output = _Output()
    p = ABPlayer(output)
    p.open(str(tmp_path / "original.wav"), str(tmp_path / "final.wav"), (-12.0, -9.0))
    _wait(lambda: p.ready)
    assert p.hasBefore and p.duration == pytest.approx(1.0) and p.matchDb == pytest.approx(3.0)
    p.play()
    sink = output.sinks[-1]
    assert sink.state == "active" and p.playing
    pulled = np.frombuffer(sink.device.read(8 * 4800).data(), dtype=np.float32).reshape(-1, 2)
    assert len(pulled) == 4800 and np.abs(pulled[1000:]).max() == pytest.approx(0.5 * 10 ** (-3 / 20), abs=0.01)
    p.choose("before")
    assert p.source == "before" and p.comparison.source == "before"
    p.seek(0.5)
    assert p.comparison.position == FS // 2
    p.pause()
    sink.device.read(8 * 4800)  # the output plays the fade out
    _wait(lambda: sink.state == "suspended")
    p.close()
    assert not p.ready and sink.state == "stopped"


def test_without_a_sound_card_the_player_says_so(app):
    from eden.gui.player import ABPlayer

    class Silent(_Output):
        available = False

    p = ABPlayer(Silent())
    assert not p.available and "Aucune sortie audio" in p.message
    p.open("", "final.wav", (None, None))
    assert not p.ready
