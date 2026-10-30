"""Second review round on the mastering and the kick/808 duck, checked by measurement: low-band
notes read from the 808's pitch and level (kicks are not notes), kick hits set on the kick's
onset so the duck lands where the documentation says, and a bus glue threshold read like its
compressor's detector."""

import re

import numpy as np
import pytest

from eden.mix import dsp, lowend
from eden.mix import master as M
from synth_voice import FS, beat, voice

BEAT_S = 60 / 140  # 140 BPM


def _kick(fs):
    """A kick whose pitch falls from 120 to 50 Hz, 300 ms."""
    t = np.arange(int(0.3 * fs)) / fs
    return np.sin(2 * np.pi * np.cumsum(50 + 70 * np.exp(-t / 0.03)) / fs) * np.exp(-t / 0.12)


def _trap_kicks(seconds):
    """Kicks on beats 1, 1¾, 2½, 3½ and 4¼ of every bar: some land on an 808 note's attack,
    the others on its tail."""
    out = np.zeros(int(seconds * FS))
    kick = _kick(FS)
    for bar in np.arange(0, seconds - 1, 4 * BEAT_S):
        for b in (0, 0.75, 1.5, 2.5, 3.25):
            start = int((bar + b * BEAT_S) * FS)
            if start + kick.size < out.size:
                out[start:start + kick.size] += kick
    return out


def _808(seconds, every_s, tau_s=0.6, vary_db=0.0, pitches=(43.65, 51.91, 58.27, 38.89), seed=0):
    """Sine 808 notes every ``every_s`` (3 ms attack, 10 ms release), decaying with ``tau_s``
    (None: held), each one up to ``vary_db`` louder or quieter than the others."""
    rng = np.random.default_rng(seed)
    out = np.zeros(int(seconds * FS))
    for i, start_s in enumerate(np.arange(0, seconds - 1, every_s)):
        start = int(start_s * FS)
        t = np.arange(min(out.size - start, int(every_s * FS))) / FS
        env = (np.exp(-t / tau_s) if tau_s else np.ones(t.size)) * np.minimum(1, t / 0.003)
        env[-int(0.01 * FS):] *= np.linspace(1, 0, int(0.01 * FS))
        level = 10 ** (rng.uniform(-vary_db, vary_db) / 20)
        out[start:start + t.size] += level * env * np.sin(2 * np.pi * pitches[i % len(pitches)] * t)
    return 0.35 * out


def _legato_808(seconds, vary_db, seed=0):
    """Held notes on one pitch (49 Hz), back to back: each one stops in 200 samples and the next
    starts at once (the master checker's case)."""
    rng = np.random.default_rng(seed)
    out = np.zeros(int(seconds * FS))
    note = int(0.857 * FS)
    t = np.arange(note) / FS
    for start in range(0, out.size - note, note):
        env = np.ones(note)
        env[-200:] = np.linspace(1, 0, 200)
        out[start:start + note] = 10 ** (rng.uniform(-vary_db, vary_db) / 20) * env * np.sin(2 * np.pi * 49 * t)
    return 0.35 * out


def _low(mono):
    """The master's band below 100 Hz."""
    return dsp.split_band(np.stack([mono, mono], 1), FS, None, M.LOW_HZ)[0]


def _spread(peaks):
    return float(np.percentile(peaks, 90) - np.percentile(peaks, 10))


# -- M1: low-band notes ------------------------------------------------------------------------

@pytest.mark.parametrize("tau_s", [0.3, 0.6, 1.5])
def test_equal_decaying_808_notes_do_not_vary(tau_s):
    peaks = M._note_peaks_db(_low(_808(20, 2 * BEAT_S, tau_s)), FS)
    assert peaks.size >= 20  # one per note (22 in 20 s)
    assert _spread(peaks) < 2.0


@pytest.mark.parametrize("tau_s", [0.3, 0.6, 1.5])
@pytest.mark.parametrize("every_beats", [2, 4])
def test_kicks_on_equal_808_notes_are_not_read_as_uneven_notes(tau_s, every_beats):
    # kicks on half of the notes' attacks and on their tails: the notes they hide are left out,
    # the kicks themselves are not notes
    x = _808(20, every_beats * BEAT_S, tau_s) + 0.45 * _trap_kicks(20)
    peaks = M._note_peaks_db(_low(x), FS)
    assert peaks.size < 4 or _spread(peaks) < 2.0


@pytest.mark.parametrize("tau_s", [0.6, 1.5])
@pytest.mark.parametrize("every_beats", [2, 4])
def test_quiet_kicks_on_the_tails_of_equal_808_notes_are_not_notes(tau_s, every_beats):
    # a kick 11 dB under the 808 beats against a note's tail, its pitch hidden by the 808's:
    # 150 ms later the level is back on the tail's decay, where a new note would still stand
    x = _808(20, every_beats * BEAT_S, tau_s) + 0.1 * _trap_kicks(20)
    peaks = M._note_peaks_db(_low(x), FS)
    assert peaks.size < 4 or _spread(peaks) < 2.0


def test_uneven_808_notes_are_found_under_quiet_kicks():
    peaks = M._note_peaks_db(_low(_808(20, 2 * BEAT_S, 0.3, 4.0) + 0.1 * _trap_kicks(20)), FS)
    assert peaks.size >= 4 and _spread(peaks) > 4.0


def test_a_slide_goes_on_with_its_note():
    # F1 sliding down to C1 on a decaying 808: the C1 after the slide has no attack of its own,
    # only the note's decay, and is not compared with the attacks
    bars = []
    for _ in range(16):
        f = np.concatenate([np.full(int(0.3 * FS), 43.65), np.geomspace(43.65, 32.70, int(0.2 * FS)),
                            np.full(int(0.5 * FS), 32.70)])
        t = np.arange(f.size) / FS
        bars += [0.35 * np.exp(-t / 0.6) * np.minimum(1, t / 0.003) * np.sin(2 * np.pi * np.cumsum(f) / FS),
                 np.zeros(int(0.1 * FS))]
    peaks = M._note_peaks_db(_low(np.concatenate(bars)), FS)
    assert peaks.size >= 14 and _spread(peaks) < 1.0


def test_kicks_louder_than_the_808_leave_most_notes_out():
    # the documented limit: notes under a louder kick, or just after one, are not compared
    x = _808(20, 2 * BEAT_S, 0.6, 4.0) + 0.45 * _trap_kicks(20)
    assert M._note_peaks_db(_low(x), FS).size < 4  # of 22 notes


def test_kicks_alone_are_not_notes():
    # their pitch falls, then their tail settles on 50 Hz: a pitch, but no note starting there
    assert M._note_peaks_db(_low(0.45 * _trap_kicks(20)), FS).size == 0


@pytest.mark.parametrize("signal", [
    pytest.param(lambda: _legato_808(20, 4.0), id="legato-held-same-pitch"),
    pytest.param(lambda: _808(20, 0.214, 0.6, 4.0), id="fast-every-0.21s"),
    pytest.param(lambda: _808(20, 2 * BEAT_S, 0.6, 4.0), id="decaying"),
])
def test_uneven_808_notes_are_found(signal):
    peaks = M._note_peaks_db(_low(signal()), FS)
    assert peaks.size >= 8 and _spread(peaks) > 4.0


def test_notes_late_in_a_song_are_read_where_they_are_at_44_1_khz():
    # a 1 ms frame is 44 samples at 44.1 kHz (0.998 ms): read as 1 ms, the pitch and the head
    # of a note 90 s in would be looked for 0.2 s after it, here in the silence after the note
    x = np.zeros(100 * FS)
    t = np.arange(int(0.25 * FS)) / FS
    note = 0.35 * np.minimum(1, t / 0.003) * np.minimum(1, (t[-1] - t) / 0.01) * np.sin(2 * np.pi * 49 * t)
    for start_s in (90, 92, 94, 96, 98):
        x[start_s * FS:start_s * FS + note.size] += note
    assert FS == 44100 and M._note_peaks_db(_low(x), FS).size == 5


def test_the_low_band_stage_says_how_many_notes_it_compared_and_how_much_they_vary(monkeypatch):
    measured = []
    real = M._note_peaks_db
    monkeypatch.setattr(M, "_note_peaks_db", lambda low, fs: measured.append(real(low, fs)) or measured[-1])
    sub = _808(20, 2 * BEAT_S, 0.6, 4.0)
    above = dsp.split_band(beat(20, level=0.2), FS, 150, None)[0]  # the 808 alone under 100 Hz
    r = M.master(above + np.stack([sub, sub], 1), FS, 1.0, tempo_bpm=140)
    low = next(t for t in r.treatments if t.label.startswith("Tenue des graves"))
    shown = re.search(r"Les crêtes des (\d+) notes graves varient de (\d+\.\d) dB", low.reason)
    assert measured[0].size >= 20 and shown and int(shown.group(1)) == measured[0].size
    assert float(shown.group(2)) == pytest.approx(_spread(measured[0]), abs=0.05)
    steady = _808(20, 2 * BEAT_S, 0.6) + 0.45 * _trap_kicks(20)
    r = M.master(above + np.stack([steady, steady], 1), FS, 1.0, tempo_bpm=140)
    assert not any(t.label.startswith("Tenue des graves") for t in r.treatments)


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
