"""Dynamics of a voice: tail-safe compression, compressor thresholds and vocal riding."""

import math

import numpy as np
import pytest
from scipy.signal import butter, fftconvolve, sosfilt

from eden.mix import dsp, riding
from eden.mix.analysis import active_frames, measure_vocal
from eden.mix.loudness import integrated_loudness
from eden.mix.treatments import _threshold, apply
from eden.mix.vocal import plan_voice, tail_hold
from synth_voice import FS, beat, voice

# -- tail-safe compression ------------------------------------------------------------------


def _classic_smooth(gain_db, attack, release, slow_release=None, slow_after=0.0):
    """The attack/release smoothing as it was before tail-safe mode changed (one state)."""
    att, rel = math.exp(-1 / attack), math.exp(-1 / release)
    slow = math.exp(-1 / slow_release) if slow_release else rel
    out, state, busy = np.empty_like(gain_db), 0.0, 0.0
    for i, target in enumerate(gain_db):
        coef = att if target < state else (slow if busy > slow_after else rel)
        state = coef * state + (1 - coef) * target
        busy = busy + 1 if target < -0.1 else (busy if state < -0.1 else 0.0)
        out[i] = state
    return out


def test_without_hold_the_smoothing_is_unchanged():
    g = np.minimum(0.0, np.random.default_rng(3).normal(-1.0, 3.0, 4000))
    assert np.array_equal(dsp._smooth(g, 2.0, 60.0, 800.0, 200.0), _classic_smooth(g, 2.0, 60.0, 800.0, 200.0))


def _phrase_then_rest():
    # a loud word (−6 dB of reduction), then quieter sound under the threshold, then a rest
    g = np.concatenate([np.full(300, -6.0), np.zeros(300), np.zeros(200)])
    power = np.concatenate([np.full(300, 1.0), np.full(300, 0.01), np.full(200, 0.001)])
    hold = np.zeros(g.size, dtype=bool)
    hold[600:] = True
    return g, power, hold


def test_tail_safe_hold_is_the_power_weighted_mean_of_the_phrase():
    g, power, hold = _phrase_then_rest()
    out = dsp._smooth(g, 1.0, 50.0, hold=hold, power=power)
    free = dsp._smooth(g, 1.0, 50.0)[:600]
    expected = 10 * math.log10(np.sum(power[:600] * 10 ** (free / 10)) / np.sum(power[:600]))
    assert np.all(out[600:] == pytest.approx(expected))
    assert expected < -5.0  # the loud word sets it: the plain time mean would be about −3 dB
    assert np.mean(free) > -3.5


def test_tail_safe_gain_never_comes_back_above_the_phrase_mean():
    g, power, hold = _phrase_then_rest()
    out = dsp._smooth(g, 1.0, 50.0, hold=hold, power=power)
    free = dsp._smooth(g, 1.0, 50.0)
    assert free[599] > -0.05  # a normal compressor is back at 0 dB under the threshold
    assert out[599] == pytest.approx(out[650], abs=0.05)  # tail-safe: it stays at the phrase's reduction


def _reverb(x, rt60, wet_db, seed=0, predelay=0.02):
    rng = np.random.default_rng(seed)
    n = int(rt60 * FS)
    ir = np.concatenate([np.zeros(int(predelay * FS)), rng.normal(size=n) * 10 ** (-3 * np.arange(n) / FS / rt60)])
    wet = fftconvolve(x[:, 0], ir)[: x.shape[0]]
    wet = np.stack([wet, wet], axis=1)
    return wet * 10 ** (wet_db / 20) * math.sqrt(np.sum(x ** 2) / np.sum(wet ** 2))


def _echo(x, delay_s, feedback_db, taps=4):
    out = np.zeros_like(x)
    d = int(delay_s * FS)
    for i in range(1, taps + 1):
        out[d * i:] += 10 ** (feedback_db * i / 20) * x[:-d * i]
    return out


@pytest.mark.parametrize("seed,spread", [(11, 10), (5, 8)])
@pytest.mark.parametrize("effect", ["reverb", "echo"])
def test_tail_safe_chain_keeps_the_fl_tails_at_the_voice_level(seed, spread, effect):
    dry = voice(seconds=25, seed=seed, phrase_spread_db=spread)
    wet = _reverb(dry, 1.5, -12.0) if effect == "reverb" else _echo(dry, 60 / 140, -6.0)  # 1/4 at 140 BPM
    full = dry + wet
    m = measure_vocal(full, FS)
    chain = [t for t in plan_voice(m, "lead_vocal", 1.0, True) if t.kind in ("compressor", "makeup")]
    y = apply(full, FS, chain, hold=tail_hold(m, full, FS, 140.0))
    assert chain[-1].params["gain_db"] > 2.0  # the compressors worked and make-up gave the loudness back
    # the chain only multiplies by a gain: apply that same gain to the voice and to the FL effect apart
    sounding = np.abs(full[:, 0]) > 1e-12
    gain = np.ones(full.shape[0])
    gain[sounding] = y[sounding, 0] / full[sounding, 0]
    voice_change = integrated_loudness(dry * gain[:, None], FS) - integrated_loudness(dry, FS)
    wet_change = 10 * math.log10(np.sum((wet * gain[:, None]) ** 2) / np.sum(wet ** 2))
    level, size = dsp.band_levels_db(dry, FS)
    rest = np.pad(np.repeat(level < -100, size), (0, full.shape[0] - level.size * size))
    rest_change = 10 * math.log10(np.sum((wet[rest] * gain[rest, None]) ** 2) / np.sum(wet[rest] ** 2))
    assert abs(wet_change - voice_change) <= 0.5
    assert abs(rest_change - voice_change) <= 0.5  # alone in the rests, the tails are not lifted either


# -- compressor thresholds ------------------------------------------------------------------

@pytest.mark.parametrize("seed,spread", [(1, 4), (3, 4), (7, 16), (11, 10)])
def test_peak_compressor_gets_its_designed_reduction_on_its_loudest_moments(seed, spread):
    x = voice(seconds=25, seed=seed, phrase_spread_db=spread)
    chain = plan_voice(measure_vocal(x, FS), "lead_vocal", 1.0, False)
    peak = next(t for t in chain if t.label.startswith("Compression des crêtes"))
    y = x
    for t in chain[: chain.index(peak)]:
        y = apply(y, FS, [t])
    p = peak.params
    threshold = _threshold(y, FS, p)
    _, sung, _ = active_frames(y, FS)
    power, _ = dsp.detector_power(y, FS)
    level = 10 * np.log10(np.maximum(power[: sung.size], 1e-20))
    top = sung & (level >= np.percentile(level[sung], p["percentile"]))
    # the threshold is set on the level the compressor's detector reads: 3 dB at its P97
    assert (1 - 1 / p["ratio"]) * (np.percentile(level[sung], p["percentile"]) - threshold) == pytest.approx(
        p["reduction_db"])
    gr, _ = dsp.compressor_gain_db(y, FS, threshold, p["ratio"], attack_ms=p["attack_ms"],
                                   release_ms=p["release_ms"], max_reduction_db=p["max_reduction_db"])
    assert 2.0 <= -np.median(gr[: sung.size][top]) <= 4.0


# -- vocal riding ---------------------------------------------------------------------------

SECONDS = 30
PHRASE = slice(15 * FS, 20 * FS)  # the 4th phrase (15–19 s) and its rest


@pytest.fixture(scope="module")
def lead():
    return voice(seed=11, phrase_spread_db=2, seconds=SECONDS)


def _fourth_phrase(v, b):
    r = riding.ride(v, b, FS, 140.0, 1.0)
    assert len(r.phrases) == 6
    return r.phrases[3]


def test_riding_leaves_a_steady_mix_alone(lead):
    assert riding.ride(lead, beat(SECONDS), FS, 140.0, 1.0).moved == 0


@pytest.mark.parametrize("residue", [0.0, 1e-5])
def test_riding_never_lowers_the_voice_where_the_beat_is_cut(lead, residue):
    b = beat(SECONDS)
    b[PHRASE] = np.random.default_rng(0).normal(0, residue, b[PHRASE].shape) if residue else 0.0
    phrase = _fourth_phrase(lead, b)
    assert phrase.exposed and phrase.gain_db == 0.0


def test_riding_never_lowers_the_voice_for_a_bar_without_beat(lead):
    b = beat(SECONDS)
    b[16 * FS:16 * FS + int(4 * 60 / 140 * FS)] *= 1e-6  # one bar at 140 BPM inside the phrase
    assert abs(_fourth_phrase(lead, b).gain_db) <= 0.5


def test_riding_never_lowers_the_voice_under_a_filter_sweep(lead):
    b = beat(SECONDS)
    b[PHRASE] = sosfilt(butter(4, 500, fs=FS, output="sos"), b[PHRASE], axis=0)
    assert abs(_fourth_phrase(lead, b).gain_db) <= 0.5


@pytest.mark.parametrize("amp", [0.1, 0.2, 0.3])  # an 808 at about −28, −22 and −19 LUFS
def test_riding_ignores_the_808_stopping_for_a_line(lead, amp):
    n = SECONDS * FS
    sub = np.zeros(n)
    hit = np.arange(FS) / FS
    for start in range(0, n - FS, FS):
        sub[start:start + FS] = amp * np.sin(2 * np.pi * 50 * hit) * np.exp(-hit)
    sub[PHRASE] = 0.0
    assert abs(_fourth_phrase(lead, beat(SECONDS) + np.stack([sub, sub], axis=1)).gain_db) <= 0.5


def test_riding_still_brings_down_a_phrase_the_voice_pushed(lead):
    v = lead.copy()
    v[PHRASE] *= 10 ** (5 / 20)
    phrase = _fourth_phrase(v, beat(SECONDS))
    assert phrase.gain_db == -riding.MAX_RIDE_DB  # a 5 dB push is brought back, capped at the rider's range


def test_riding_brings_the_voice_up_when_the_beat_gets_louder(lead):
    b = beat(SECONDS)
    b[PHRASE] *= 2.0
    assert _fourth_phrase(lead, b).gain_db == riding.MAX_RIDE_DB  # the louder beat justifies the full range


def test_riding_finds_the_phrases_of_a_quietly_rendered_voice(lead):
    b = beat(SECONDS)
    quiet = lead * 10 ** (-45 / 20)  # peaks near −57 dBFS
    assert riding.phrase_levels(quiet, b, FS, 140.0)[0] == riding.phrase_levels(lead, b, FS, 140.0)[0]
