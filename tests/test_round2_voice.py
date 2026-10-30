"""A voice's chain, round 2: a compressor that only lowers the level is not applied, the low-mid
threshold keeps clean voices out, and the high-pass also listens to the rests between phrases."""

import math
from pathlib import Path

import numpy as np
import pytest
from scipy.signal import butter, fftconvolve, sosfilt

from eden.mix import dsp
from eden.mix.analysis import REST_WINDOW_S, _rest_low_spectrum, active_frames, measure_vocal
from eden.mix.dsp import apply_sos, peaking_sos, shelf_sos
from eden.mix.engine import _chain
from eden.mix.parts import Part
from eden.mix.treatments import IDLE_DB, STEADY_PERCENTILE, Treatment, _moves, apply
from eden.mix.vocal import (HIGHPASS_REST_TRIGGER_DB, HIGHPASS_TRIGGER_DB, LOW_MID_MIN_DB, PROFILES, plan_voice,
                            tail_hold)
from synth_voice import FS, voice

DEEP = [73, 82, 98, 110]


def _plan(m, role="lead_vocal"):
    return plan_voice(m, role, 1.0, False)


# -- V1: a dynamic stage whose reduction does not move is not applied ------------------------------

def _echo(x, delay_s, feedback_db, taps=4):
    out = np.zeros_like(x)
    d = int(delay_s * FS)
    for i in range(1, taps + 1):
        out[d * i:] += 10 ** (feedback_db * i / 20) * x[:-d * i]
    return out


@pytest.fixture(scope="module")
def echoed():
    """A voice whose FL chain holds a 1/4-note echo at −6 dB (140 BPM): the echo fills the rests."""
    dry = voice(seconds=40, seed=1, phrase_spread_db=4)
    return dry + _echo(dry, 60 / 140, -6.0)


def test_a_tail_safe_leveling_stage_that_became_a_fixed_gain_is_not_applied(echoed):
    m = measure_vocal(echoed, FS)
    plan = plan_voice(m, "lead_vocal", 1.0, True)
    leveling = next(t for t in plan if t.label.startswith("Compression de niveau"))
    peaks = next(t for t in plan if t.label.startswith("Compression des crêtes"))
    hold = tail_hold(m, echoed, FS, 140.0)
    assert hold.mean() < 0.001  # the echo hides the rests: the phrase floor runs over the whole song
    apply(echoed, FS, plan, hold=hold)
    # it reduced 3 dB nearly everywhere: a fixed gain the make-up gave back, shown as "2.0:1" before
    assert leveling.label == "Compression de niveau 2.0:1"
    assert leveling.measured["reduction_max_db"] >= 2.9 and not leveling.applied
    assert peaks.applied and plan[-1].kind == "makeup" and plan[-1].applied


def test_the_mix_report_does_not_show_a_stage_that_only_lowered_the_level(echoed):
    _, _, _, result = _chain(Part("ch1", "Lead", "lead_vocal", echoed), FS, 1.0, "untracked", 140.0)
    labels = [t.label for t in result.treatments]
    assert not any(label.startswith("Compression de niveau") for label in labels), labels
    assert any(label.startswith("Compression des crêtes") for label in labels), labels


def test_a_fixed_reduction_is_not_applied_and_a_moving_one_is():
    x = voice(seconds=8, seed=3)
    n = active_frames(x, FS)[1].size
    fixed = np.full(n, -3.0)
    assert not _moves(fixed, x, FS)
    moving = fixed.copy()
    moving[1000:1100] = -3.0 - 0.5 * IDLE_DB  # a 100 ms word reduced 0.15 dB more than the rest: still fixed
    assert not _moves(moving, x, FS)
    moving[1000:1100] = -3.0 - 1.5 * IDLE_DB  # 0.45 dB more: it moves
    assert _moves(moving, x, FS)
    assert not _moves(np.full(n, -IDLE_DB / 2), x, FS)  # never reduces IDLE_DB, as before
    assert _moves(np.where(np.arange(n) % 500 < 20, -IDLE_DB, 0.0), x, FS)  # rare, but it moves
    assert STEADY_PERCENTILE == 95.0
    # a compressor far under the signal with a cap: −3 dB on every sung moment, nothing else
    stage = Treatment("compressor", "Compression", "test", {"threshold_db": -120.0, "ratio": 4.0, "attack_ms": 5.0,
                                                            "release_ms": 100.0, "max_reduction_db": 3.0})
    out = apply(x, FS, [stage])
    assert stage.measured["reduction_max_db"] == pytest.approx(3.0, abs=0.01)
    assert not stage.applied and np.array_equal(out, x)


@pytest.mark.parametrize("seed,spread", [(7, 16), (11, 10)])
def test_compressors_that_level_the_voice_are_still_applied(seed, spread):
    x = voice(seconds=25, seed=seed, phrase_spread_db=spread)
    plan = _plan(measure_vocal(x, FS))
    apply(x, FS, plan)
    compressors = [t for t in plan if t.kind == "compressor"]
    assert len(compressors) == 2 and all(t.applied for t in compressors)


def _few_piercing_s(seed, count):
    """A voice with almost no sibilance, plus ``count`` piercing 's' (their peak 1.5 × the voice's)."""
    x = voice(seed=seed, sibilance=0.05)
    rng = np.random.default_rng(100 + seed)
    sos = butter(4, [5000, 9500], btype="bandpass", fs=FS, output="sos")
    for start in rng.choice(np.arange(FS, x.shape[0] - FS, int(0.18 * FS)), size=count, replace=False):
        burst = sosfilt(sos, rng.normal(0, 1, 3000)) * np.hanning(3000)
        x[start:start + 3000] += (1.5 * 0.25 * burst / np.max(np.abs(burst)))[:, None]
    return x


@pytest.mark.parametrize("seed", [3, 7])
def test_a_deesser_on_a_few_piercing_s_is_applied(seed, monkeypatch):
    x = _few_piercing_s(seed, 4)
    plan = _plan(measure_vocal(x, FS))
    deessers = [t for t in plan if t.kind == "deesser"]
    curves = []
    original = dsp.deess_gain_db

    def spy(*args, **kw):
        out = original(*args, **kw)
        curves.append((args[0], out[2]))  # the signal the de-esser received and its reduction curve
        return out

    monkeypatch.setattr(dsp, "deess_gain_db", spy)
    apply(x, FS, plan)
    assert len(deessers) == 2 and all(t.applied for t in deessers), [(t.label, t.measured) for t in plan]
    for (received, gr), t in zip(curves, deessers, strict=True):
        assert t.measured["reduction_max_db"] > 2.5
        _, active, _ = active_frames(received, FS)
        sung = gr[: active.size][active[: gr.size]]
        # about 5 % of the sung moments: a rule on the 5th..95th percentiles would have dropped it
        assert 0.03 < np.mean(sung < -0.05) < 0.08
        assert np.percentile(sung, 95) - np.percentile(sung, 5) < IDLE_DB


# -- V2: the low-mid threshold keeps clean voices with lowest notes 220–247 Hz out ---------------------

def _warm(notes, seed, shelf_db):
    return apply_sos(voice(seed=seed, notes=notes), shelf_sos(FS, 300, shelf_db, high=False))


# every note pooled they read 2.28 to 2.76 dB (the highest clean value of seeds 1–8 with mud > 6 dB); since
# round 3 a bump must be seen on two notes (tests/test_round3_lowmid.py): none is, they read 0 dB
@pytest.mark.parametrize("notes,seed,shelf_db", [
    ([247, 277, 311, 330, 370], 2, 1.4),
    ([247, 277, 311, 330, 370], 2, 3.0),
    ([240, 270, 300, 320, 360], 2, 1.4),
    ([233, 262, 294, 330, 349, 392], 2, 3.0),
    ([220, 247, 262, 294, 330], 2, 0.0),
])
def test_a_clean_voice_with_lowest_notes_220_to_247_hz_gets_no_low_mid_cut(notes, seed, shelf_db):
    m = measure_vocal(_warm(notes, seed, shelf_db), FS)
    # their 2nd harmonics fall on the vowels' first formant, just under 500 Hz
    assert m.low_mid_excess_db == 0.0 and m.mud_db > 6.0
    assert not [t.label for t in _plan(m) if t.label.startswith("Bas-médiums")]


@pytest.mark.parametrize("freq,q,seed,measured", [(300, 2.0, 5, 2.97), (300, 4.0, 7, 3.00), (200, 2.0, 1, 4.15),
                                                  (400, 2.0, 4, 3.16)])
def test_the_acceptance_bumps_still_arm_the_low_mid_cut(freq, q, seed, measured):
    # +6 dB bumps; each case is the seed (of 1–8) where the bump reads lowest
    m = measure_vocal(apply_sos(voice(seed=seed), peaking_sos(FS, freq, q, 6.0)), FS)
    assert m.low_mid_excess_db == pytest.approx(measured, abs=0.01) and m.low_mid_excess_db >= LOW_MID_MIN_DB
    cut = [t for t in _plan(m) if t.label.startswith("Bas-médiums")]
    assert cut and abs(math.log2(cut[0].params["freq_hz"] / freq)) <= 1 / 6


# -- V3: the high-pass also reads the rests between phrases --------------------------------------------

def _hp(m, role):
    hp = PROFILES[role].highpass_hz
    return min(hp, 0.9 * m.lowest_f0_hz) if m.lowest_f0_hz else hp


@pytest.mark.parametrize("notes", [None, DEEP], ids=["default", "deep"])
@pytest.mark.parametrize("seed", range(1, 9))
def test_a_rumble_under_the_singing_is_found_in_the_rests(seed, notes):
    m = measure_vocal(voice(seed=seed, notes=notes, rumble=0.02), FS)  # about −60 dBFS RMS
    for role in ("lead_vocal", "double", "back_vocal"):
        hp = _hp(m, role)
        sung, rests = m.energy_below_db(hp / 2), m.rest_energy_below_db(hp)
        cut = [t for t in _plan(m, role) if t.kind == "highpass"]
        # while the voice sings, this rumble does not stand out of its attacks: only the rests show it
        assert sung <= HIGHPASS_TRIGGER_DB, (role, sung)
        assert rests > HIGHPASS_REST_TRIGGER_DB and cut, (role, sung, rests)
        assert cut[0].params["freq_hz"] == pytest.approx(hp)
        assert cut[0].reason.startswith(
            f"Bruit grave dans les silences entre les phrases (grondement, manipulation du micro) : {rests:.0f} dB "
            f"sous {hp:.0f} Hz (la coupe à 100 %) par rapport à la voix chantée ; note la plus grave")
        assert "pendant le chant" not in cut[0].reason


def test_the_rest_measure_is_the_power_under_the_cut_relative_to_the_sung_voice():
    t = np.arange(12 * FS) / FS
    sung = (t % 1.0) < 0.5  # 0.5 s lines, 0.5 s rests
    hum = 0.003 * np.sin(2 * np.pi * 40 * t)  # 40 dB under the voice, everywhere
    x = np.stack([0.3 * np.sin(2 * np.pi * 200 * t) * sung + hum] * 2, axis=1)
    m = measure_vocal(x, FS)
    assert m.rest_energy_below_db(80.0) == pytest.approx(-40.0, abs=0.3)
    assert m.rest_energy_below_db(30.0) < -60.0  # read 4 Hz apart: the hum is not under 30 Hz
    assert np.all(np.diff(m.rest_low_hz) == pytest.approx(1 / REST_WINDOW_S, rel=0.01))


@pytest.mark.parametrize("shift_ms", range(0, 64, 3))
def test_a_rest_a_little_longer_than_the_window_is_read_wherever_it_falls(shift_ms):
    t = np.arange(6 * FS) / FS
    start = 3.0 + shift_ms / 1000
    # one silence of 280 ms, read as a rest of 257 ms (the decimation and the 10 ms average blur its edges):
    # a grid of windows every 62 ms missed it more often than not
    sung = (t < start) | (t >= start + 0.28)
    x = np.stack([0.3 * np.sin(2 * np.pi * 200 * t) * sung + 0.003 * np.sin(2 * np.pi * 40 * t)] * 2, axis=1)
    freqs, share = _rest_low_spectrum(x, FS, 0.3 ** 2 / 2)
    assert 10 * math.log10(share[freqs < 80].sum()) == pytest.approx(-40.0, abs=0.3)


def test_a_voice_that_never_rests_long_enough_has_no_rest_measure():
    t = np.arange(12 * FS) / FS
    x = np.stack([0.3 * np.sin(2 * np.pi * 200 * t) * ((t % 0.4) < 0.25) + 0.003 * np.sin(2 * np.pi * 40 * t)] * 2,
                 axis=1)  # rests of 150 ms only
    m = measure_vocal(x, FS)
    assert m.rest_low_share.size == 0 and m.rest_energy_below_db(80.0) == -math.inf


@pytest.mark.parametrize("seed,notes", [(3, None), (5, DEEP)])
def test_a_loud_rumble_does_not_hide_the_rests_and_both_measures_are_stated(seed, notes):
    m = measure_vocal(voice(seed=seed, notes=notes, rumble=0.04), FS)  # about −54 dBFS RMS
    hp = _hp(m, "lead_vocal")
    sung, rests = m.energy_below_db(hp / 2), m.rest_energy_below_db(hp)
    # judged on the full band's 1 ms frames (the sung frames' rule), this rumble left no rest of 250 ms
    assert sung > HIGHPASS_TRIGGER_DB and rests > HIGHPASS_REST_TRIGGER_DB
    reason = next(t for t in _plan(m) if t.kind == "highpass").reason
    assert reason.startswith(f"Grondement ou plosives pendant le chant : {sung:.0f} dB de l'énergie de la voix sous "
                             f"{hp / 2:.0f} Hz (une octave sous {hp:.0f} Hz, la coupe à 100 %) ; bruit grave dans les "
                             f"silences entre les phrases (grondement, manipulation du micro) : {rests:.0f} dB")


def _pink(n, seed, rms_dbfs):
    rng = np.random.default_rng(1000 + seed)
    spectrum = np.fft.rfft(rng.normal(size=n))
    f = np.fft.rfftfreq(n, 1 / FS)
    spectrum[1:] /= np.sqrt(f[1:])
    spectrum[0] = 0
    y = np.fft.irfft(spectrum, n)
    return y / np.sqrt(np.mean(y ** 2)) * 10 ** (rms_dbfs / 20)


def _reverb(x, rt60, wet_db, seed=0):
    rng = np.random.default_rng(seed)
    n = int(rt60 * FS)
    ir = np.concatenate([np.zeros(int(0.02 * FS)), rng.normal(size=n) * 10 ** (-3 * np.arange(n) / FS / rt60)])
    wet = fftconvolve(x[:, 0], ir)[: x.shape[0]]
    return x + np.stack([wet, wet], axis=1) * 10 ** (wet_db / 20) * math.sqrt(np.sum(x[:, 0] ** 2) / np.sum(wet ** 2))


@pytest.mark.parametrize("seed,notes", [(1, None), (4, None), (2, DEEP), (7, DEEP)])
def test_a_clean_voice_in_a_quiet_room_or_with_its_fl_reverb_is_not_high_passed(seed, notes):
    dry = voice(seed=seed, notes=notes)
    room = dry + _pink(dry.shape[0], seed, -70.0)[:, None]  # a quiet room's noise floor in the rests
    for x in (room, _reverb(dry, 1.5, -12.0)):  # the reverb's tails fill the rests
        m = measure_vocal(x, FS)
        for role in ("lead_vocal", "double", "back_vocal"):
            assert m.rest_energy_below_db(_hp(m, role)) < HIGHPASS_REST_TRIGGER_DB - 5
            assert not [t for t in _plan(m, role) if t.kind == "highpass"], role


# -- docs/mixage.md tells what the code does -------------------------------------------------------------

def _french(value):
    return f"{value:g}".replace(".", ",").replace("-", "−")


def test_the_docs_state_the_round2_voice_rules():
    doc = (Path(__file__).resolve().parent.parent / "docs" / "mixage.md").read_text(encoding="utf-8")
    section = doc.split("## 2. ")[1].split("## 3. ")[0].replace("\n", " ")
    assert f"{_french(IDLE_DB)} dB" in section and f"{STEADY_PERCENTILE:.0f} %" in section
    assert f"> {_french(HIGHPASS_REST_TRIGGER_DB)} dB" in section and f"{REST_WINDOW_S * 1000:.0f} ms" in section
    assert f"bosse ≥ {_french(LOW_MID_MIN_DB)} dB" in section
    careful = doc.split("**Voix « prudente »**")[1].split("\n- ")[0].replace("\n", " ")
    assert "ne bouge pas d'au moins 0,3 dB" in careful
