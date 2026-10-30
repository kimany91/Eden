"""Second review round on the mastering and the kick/808 duck, checked by measurement: kick hits
set on the kick's onset so the duck lands where the documentation says, and a bus glue threshold
read like its compressor's detector."""

import numpy as np
import pytest

from eden.mix import dsp, lowend
from eden.mix import master as M
from synth_voice import FS, beat, voice


def _kick(fs):
    """A kick whose pitch falls from 120 to 50 Hz, 300 ms."""
    t = np.arange(int(0.3 * fs)) / fs
    return np.sin(2 * np.pi * np.cumsum(50 + 70 * np.exp(-t / 0.03)) / fs) * np.exp(-t / 0.12)


# -- M2: kick hits on the kick's onset ------------------------------------------------------------

def _kicks_at_known_onsets(fs, seconds=12.0):
    rng = np.random.default_rng(0)
    kick = _kick(fs)
    drums, onsets = 0.01 * rng.normal(0, 1, int(seconds * fs)), []
    for start_s in np.arange(0.5, seconds - 1, 0.6):
        start = int(start_s * fs) + int(rng.integers(0, fs // 100))  # anywhere within a 1 ms frame
        drums[start:start + kick.size] += kick
        onsets.append(start)
    return np.stack([drums, drums], 1), np.array(onsets)


@pytest.mark.parametrize("fs", [44100, 48000, 96000])
def test_kick_hits_are_set_on_the_kick_onset(fs):
    drums, onsets = _kicks_at_known_onsets(fs)
    hits = lowend._onsets(drums, fs)
    assert hits.size == onsets.size
    error_ms = hits - onsets / round(fs / 1000)  # hits are 1 ms frames
    assert abs(np.median(error_ms)) <= 2.0 and np.abs(error_ms).max() <= 2.0


def test_the_808_duck_is_down_when_the_kick_hits_and_holds_30_ms():
    fs = 48000
    drums, onsets = _kicks_at_known_onsets(fs, 6.0)
    level = np.full(drums.shape, 0.5)  # a constant goes whole through the low band: the output is the gain
    gain_db = 20 * np.log10(lowend.duck_low_band(level, fs, lowend._onsets(drums, fs), 3.0)[:, 0] / 0.5)
    ms = fs // 1000
    for onset in onsets:
        assert gain_db[onset - 8 * ms] > -0.1  # the 5 ms ramp has not started
        assert gain_db[onset] < -2.7  # fully down when the kick hits
        assert gain_db[onset + 28 * ms] < -2.7  # held 30 ms after it
        assert -2.2 < gain_db[onset + 50 * ms] < -0.5  # then released over 100 ms


# -- M3: bus glue threshold ----------------------------------------------------------------------

def test_bus_glue_takes_1_5_dB_at_the_loud_passages_as_its_detector_reads_them(monkeypatch):
    seen = {}
    real = M.apply

    def spy(x, fs, treatments, *args, **kwargs):
        if treatments[0].label.startswith("Compression de bus"):
            seen["input"], seen["stage"] = x, treatments[0]
        return real(x, fs, treatments, *args, **kwargs)

    monkeypatch.setattr(M, "apply", spy)
    M.master(voice(16, seed=11, level=0.3) + beat(16, level=0.3), FS, 1.0, tempo_bpm=140)
    stage = seen["stage"]
    power, _ = dsp.detector_power(seen["input"], FS)  # 5 ms, the compressor's own detector
    level = 10 * np.log10(np.maximum(power, 1e-20))
    loud = float(np.percentile(level[level > -80.0], 90))
    slope = 1 - 1 / stage.params["ratio"]
    assert (loud - stage.params["threshold_db"]) * slope == pytest.approx(1.5, abs=0.01)
    assert "soit 1.5 dB de réduction à leur niveau" in stage.reason
