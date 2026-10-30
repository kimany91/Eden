"""Listening in Eden: the song as FL Studio renders it (before) and Eden's mix and master (after).

Both play on one playhead: switching from one to the other keeps the exact moment, with a 10 ms
crossfade so that nothing clicks (seeking, starting and pausing are faded the same way). With
"même volume" on, the louder one is lowered to the other's loudness (BS.1770, measured when the
mix was made): a louder version always sounds better at first, and the comparison would judge
the volume, not the mix.

``Comparison`` is the sound (numpy, testable without a sound card); ``ABPlayer`` hands it to Qt's
audio output, which pulls the samples as it plays them.
"""

from __future__ import annotations

import math
from fractions import Fraction
from pathlib import Path

import numpy as np
from PySide6.QtCore import Property, QIODevice, QObject, QThread, QTimer, Signal, Slot

FADE_S = 0.01
SOURCES = ("before", "after")


class Comparison:
    """Two versions of a song on one playhead (stereo float32 at ``fs``)."""

    def __init__(self, before: np.ndarray | None, after: np.ndarray, fs: int,
                 loudness: tuple[float | None, float | None] = (None, None)) -> None:
        n = max(len(after), len(before) if before is not None else 0)
        self.fs = fs
        self.frames = n
        self.tracks = {"after": _fit(after, n)}
        if before is not None:
            self.tracks["before"] = _fit(before, n)
        self.loudness = dict(zip(SOURCES, loudness, strict=True))
        self.source = "after"
        self.matched = True
        self.position = 0
        self.playing = False
        self.ended = False
        self._fade = max(1, int(FADE_S * fs))
        self._from: tuple[str, int, float] | None = None  # what fades out: source, position, gain
        self._left = 0  # frames of that crossfade still to play
        self._level = 0.0  # 0 → 1 while starting, 1 → 0 while pausing
        self._target = 0.0

    @property
    def has_before(self) -> bool:
        return "before" in self.tracks

    def gain(self, source: str) -> float:
        """Linear gain of ``source``: with ``matched``, the louder version comes down to the other."""
        if not self.matched:
            return 1.0
        values = [v for v in self.loudness.values() if v is not None and math.isfinite(v)]
        own = self.loudness.get(source)
        if len(values) < 2 or own is None or not math.isfinite(own):
            return 1.0
        return 10 ** ((min(values) - own) / 20)

    def match_db(self) -> float:
        """How much "même volume" lowers the louder version (0 when it cannot be worked out)."""
        values = [v for v in self.loudness.values() if v is not None and math.isfinite(v)]
        return max(values) - min(values) if len(values) == 2 else 0.0

    def _crossfade_from(self, source: str, position: int, gain: float) -> None:
        self._from = (source, position, gain)
        self._left = self._fade

    def switch(self, source: str) -> None:
        if source == self.source or source not in self.tracks:
            return
        self._crossfade_from(self.source, self.position, self.gain(self.source))
        self.source = source

    def set_matched(self, matched: bool) -> None:
        if matched == self.matched:
            return
        old = self.gain(self.source)
        self.matched = matched
        self._crossfade_from(self.source, self.position, old)

    def seek(self, frame: int) -> None:
        frame = max(0, min(self.frames, int(frame)))
        if self.playing:
            self._crossfade_from(self.source, self.position, self.gain(self.source))
        self.position = frame
        self.ended = False

    def play(self) -> None:
        if self.position >= self.frames:
            self.position = 0
        self.playing, self.ended, self._target = True, False, 1.0

    def pause(self) -> None:
        self._target = 0.0  # faded out by read(); ``playing`` turns off once silent

    def _segment(self, source: str, start: int, count: int) -> np.ndarray:
        out = np.zeros((count, 2), dtype=np.float32)
        end = min(self.frames, start + count)
        if end > start:
            out[:end - start] = self.tracks[source][start:end]
        return out

    def read(self, count: int) -> np.ndarray:
        """The next ``count`` frames as they should be heard (silence once paused or ended)."""
        if not self.playing:
            return np.zeros((count, 2), dtype=np.float32)
        out = self._segment(self.source, self.position, count) * self.gain(self.source)
        if self._left > 0:  # crossfade from what was playing just before
            source, position, gain = self._from
            k = min(self._left, count)
            ramp = (np.arange(self._fade - self._left, self._fade - self._left + k, dtype=np.float32)
                    + 1) / self._fade
            old = self._segment(source, position, k) * gain
            out[:k] = old * (1 - ramp[:, None]) + out[:k] * ramp[:, None]
            self._from = (source, position + k, gain)
            self._left -= k
        # start / pause: a short ramp of the whole output
        step = 1.0 / self._fade
        if self._level != self._target:
            levels = np.clip(self._level + step * np.arange(1, count + 1) * (1 if self._target > self._level else -1),
                             0.0, 1.0).astype(np.float32)
            out *= levels[:, None]
            self._level = float(levels[-1])
        if self._level == 0.0 and self._target == 0.0:
            self.playing = False
        self.position = min(self.frames, self.position + count)
        if self.position >= self.frames:
            self.ended = True
        return out


def _fit(x: np.ndarray, n: int) -> np.ndarray:
    """Stereo float32 of ``n`` frames (mono doubled, padded with silence)."""
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 1:
        x = x[:, None]
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    x = x[:, :2]
    if len(x) < n:
        x = np.concatenate([x, np.zeros((n - len(x), 2), dtype=np.float32)])
    return np.ascontiguousarray(x)


def load_comparison(before: str | None, after: str, loudness: tuple[float | None, float | None],
                    rate: int | None = None) -> Comparison:
    """Read both WAVs (``before`` may be missing), at the output's ``rate`` when given."""
    import soundfile as sf

    data, fs = sf.read(after, dtype="float32", always_2d=True)
    original = None
    if before and Path(before).is_file():
        original, fs_before = sf.read(before, dtype="float32", always_2d=True)
        if fs_before != fs:
            original = _resample(original, fs_before, fs)
    if rate and rate != fs:
        data = _resample(data, fs, rate)
        original = _resample(original, fs, rate) if original is not None else None
        fs = rate
    return Comparison(original, data, int(fs), loudness)


def _resample(x: np.ndarray, fs: int, rate: int) -> np.ndarray:
    from scipy.signal import resample_poly

    ratio = Fraction(rate, fs).limit_denominator(1000)
    return resample_poly(x, ratio.numerator, ratio.denominator, axis=0).astype(np.float32)


# -- Qt: the audio output pulls the comparison as it plays ------------------------------------


class _Feed(QIODevice):
    """What the audio output reads: the comparison's next frames, endlessly."""

    def __init__(self, player: ABPlayer) -> None:
        super().__init__()
        self.player = player

    def readData(self, maxlen: int) -> bytes:
        return self.player._pull(maxlen)

    def writeData(self, data) -> int:
        return 0

    def bytesAvailable(self) -> int:
        return (1 << 20) + super().bytesAvailable()

    def isSequential(self) -> bool:
        return True


class _Load(QThread):
    done = Signal(object, str)  # Comparison (or None), error

    def __init__(self, before: str, after: str, loudness: tuple, rate: int | None) -> None:
        super().__init__()
        self.args = (before, after, loudness, rate)

    def run(self) -> None:
        try:
            self.done.emit(load_comparison(*self.args), "")
        except Exception as exc:  # unreadable file: said, never raised in the interface
            self.done.emit(None, f"Écoute impossible : {exc}")


class _QtOutput:
    """The PC's default audio output."""

    def __init__(self) -> None:
        try:
            from PySide6.QtMultimedia import QMediaDevices
        except ImportError:  # Qt Multimedia cannot load (a system audio library is missing): no listening
            self.device = None
            return
        self.device = QMediaDevices.defaultAudioOutput()

    @property
    def available(self) -> bool:
        return self.device is not None and not self.device.isNull()

    def format(self, fs: int):
        """(QAudioFormat, bytes per frame): float stereo at ``fs``, else what the output prefers."""
        from PySide6.QtMultimedia import QAudioFormat

        fmt = QAudioFormat()
        fmt.setChannelCount(2)
        fmt.setSampleRate(fs)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
        if not self.device.isFormatSupported(fmt):
            fmt.setSampleRate(self.device.preferredFormat().sampleRate())
        if not self.device.isFormatSupported(fmt):
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        return fmt

    def sink(self, fmt, parent):
        from PySide6.QtMultimedia import QAudioSink

        return QAudioSink(self.device, fmt, parent)


class ABPlayer(QObject):
    """Before / after player of the result page (``controller.player``)."""

    availableChanged = Signal()
    readyChanged = Signal()
    playingChanged = Signal()
    sourceChanged = Signal()
    matchedChanged = Signal()
    positionChanged = Signal()
    durationChanged = Signal()
    hasBeforeChanged = Signal()
    matchDbChanged = Signal()
    messageChanged = Signal()

    def __init__(self, output=None) -> None:
        super().__init__()
        self._output = output or _QtOutput()
        self._available = self._output.available
        self._ready = False
        self._playing = False
        self._source = "after"
        self._matched = True
        self._position = 0.0
        self._duration = 0.0
        self._hasBefore = False
        self._matchDb = 0.0
        self._message = "" if self._available else "Aucune sortie audio sur ce PC : l'écoute n'est pas possible."
        self.comparison: Comparison | None = None
        self._sink = None
        self._feed: _Feed | None = None
        self._int16 = False
        self._loader: _Load | None = None
        self._format = None
        self._sink_started = False
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)

    available = Property(bool, lambda self: self._available, notify=availableChanged)
    ready = Property(bool, lambda self: self._ready, notify=readyChanged)
    playing = Property(bool, lambda self: self._playing, notify=playingChanged)
    source = Property(str, lambda self: self._source, notify=sourceChanged)
    matched = Property(bool, lambda self: self._matched, notify=matchedChanged)
    position = Property(float, lambda self: self._position, notify=positionChanged)
    duration = Property(float, lambda self: self._duration, notify=durationChanged)
    hasBefore = Property(bool, lambda self: self._hasBefore, notify=hasBeforeChanged)
    matchDb = Property(float, lambda self: self._matchDb, notify=matchDbChanged)
    message = Property(str, lambda self: self._message, notify=messageChanged)

    def _set(self, name: str, value) -> None:
        if getattr(self, f"_{name}") != value:
            setattr(self, f"_{name}", value)
            getattr(self, f"{name}Changed").emit()

    # -- loading a version -----------------------------------------------------------------
    def open(self, before: str, after: str, loudness: tuple[float | None, float | None]) -> None:
        """Load a mix version to compare with the original (in the background)."""
        self.close()
        if not self._available or not after:
            return
        import soundfile as sf

        try:
            fs = sf.info(after).samplerate
        except RuntimeError as exc:
            self._set("message", f"Écoute impossible : {exc}")
            return
        fmt = self._output.format(fs)
        self._format = fmt
        self._set("message", "Préparation de l'écoute…")
        self._loader = _Load(before, after, loudness, fmt.sampleRate() if fmt.sampleRate() != fs else None)
        self._loader.done.connect(self._loaded)
        self._loader.start()

    def _loaded(self, comparison: Comparison | None, error: str) -> None:
        if comparison is None:
            self._set("message", error)
            return
        from PySide6.QtMultimedia import QAudioFormat

        self.comparison = comparison
        comparison.source, comparison.matched = self._source, self._matched
        if comparison.source not in comparison.tracks:
            comparison.source = "after"
        self._int16 = self._format.sampleFormat() == QAudioFormat.SampleFormat.Int16
        self._feed = _Feed(self)
        self._feed.open(QIODevice.OpenModeFlag.ReadOnly)
        self._sink = self._output.sink(self._format, self)
        self._set("source", comparison.source)
        self._set("hasBefore", comparison.has_before)
        self._set("matchDb", comparison.match_db())
        self._set("duration", comparison.frames / comparison.fs)
        self._set("position", 0.0)
        self._set("message", "" if comparison.has_before else
                  "Le morceau d'origine n'est pas enregistré avec ce mix : seule la version d'Eden s'écoute.")
        self._set("ready", True)

    def close(self) -> None:
        """Stop and let the audio go (a new mix, another version, the end of the app)."""
        if self._loader is not None and self._loader.isRunning():  # a version still loading is dropped
            self._loader.done.disconnect()
            self._loader.wait()
        self._loader = None
        if self._sink is not None:
            self._sink.stop()
            self._sink.deleteLater()
        if self._feed is not None:
            self._feed.close()
        self._sink = self._feed = self.comparison = None
        self._sink_started = False
        self._timer.stop()
        self._set("playing", False)
        self._set("ready", False)
        self._set("position", 0.0)
        self._set("duration", 0.0)

    # -- what the page asks -------------------------------------------------------------------
    @Slot()
    def toggle(self) -> None:
        if self._playing:
            self.pause()
        else:
            self.play()

    @Slot()
    def play(self) -> None:
        if self.comparison is None or self._sink is None:
            return
        self.comparison.play()
        if self._sink_started:
            self._sink.resume()
        else:
            self._sink.start(self._feed)
            self._sink_started = True
        self._set("playing", True)
        self._timer.start()

    @Slot()
    def pause(self) -> None:
        if self.comparison is not None:
            self.comparison.pause()  # faded out; the output is suspended once silent (_tick)
        self._set("playing", False)

    @Slot(str)
    def choose(self, source: str) -> None:
        if self.comparison is not None and source in self.comparison.tracks:
            self.comparison.switch(source)
            self._set("source", source)

    @Slot(bool)
    def setMatched(self, matched: bool) -> None:
        if self.comparison is not None:
            self.comparison.set_matched(matched)
        self._set("matched", matched)

    @Slot(float)
    def seek(self, seconds: float) -> None:
        if self.comparison is not None:
            self.comparison.seek(int(seconds * self.comparison.fs))
            self._set("position", seconds)

    # -- the output pulls; the page follows -------------------------------------------------------
    def _bytes_per_frame(self) -> int:
        return 4 if self._int16 else 8

    def _pull(self, maxlen: int) -> bytes:
        if self.comparison is None:
            return b""
        frames = self.comparison.read(maxlen // self._bytes_per_frame())
        if self._int16:
            return (np.clip(frames, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        return frames.tobytes()

    def _tick(self) -> None:
        c = self.comparison
        if c is None:
            return
        buffered = 0
        if self._sink is not None:
            buffered = max(0, self._sink.bufferSize() - self._sink.bytesFree()) // self._bytes_per_frame()
        self._set("position", max(0, c.position - buffered) / c.fs)
        if c.ended and c.playing:  # the end of the song: back to its start, paused
            c.pause()
            self._set("playing", False)
        if not c.playing:
            if c.ended:
                c.seek(0)
                self._set("position", 0.0)
            self._sink.suspend()
            self._timer.stop()
