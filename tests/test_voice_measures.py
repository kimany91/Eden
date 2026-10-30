"""The measurements a voice's chain is decided on: stereo, resonances, low mids, de-essing, high-pass."""

import math
import re
import tracemalloc
from pathlib import Path

import numpy as np
import pytest
from scipy.signal import resample_poly, stft

from eden.mix import dsp
from eden.mix.analysis import (FREQUENT_NOTE_SHARE, RESONANCE_MIN_DB, SILENCE_DB, HarmonicProfile, Resonance,
                               VocalMeasure, _band_power, _inside_phrases, active_frames, deess_band_low_hz,
                               find_resonances, frequent_pitches, level_of, low_mid_buildup, measure_vocal,
                               near_sung_notes, sibilant_frames, sibilant_peak, vowel_level)
from eden.mix.dsp import apply_sos, peaking_sos, shelf_sos
from eden.mix.loudness import block_loudness, gated_loudness
from eden.mix.treatments import apply
from eden.mix.vocal import HIGHPASS_TRIGGER_DB, LOW_MID_MIN_DB, PROFILES, plan_voice
from synth_voice import FS, voice

DEEP = [73, 82, 98, 110]


def _plan(m, role="lead_vocal"):
    return plan_voice(m, role, 1.0, False)


def _octaves(a, b):
    return abs(math.log2(a / b))


# -- a voice widened in FL is measured as it is heard, not through a mono fold ---------------

def _widened(v, how):
    x = v.copy()
    if how == "anti-phase":
        x[:, 1] = -0.5 * v[:, 0]
    else:
        d = int(round(how * FS / 1000))
        x[d:, 1] = v[:-d, 1]
        x[:d, 1] = 0
    return x


@pytest.mark.parametrize("seed,cases", [(3, [0.3, 0.6, 1.0, 12.0, 20.0, "anti-phase"]), (5, [0.6, 1.0])])
def test_a_widened_voice_keeps_its_sibilance_and_gets_no_comb_resonance(seed, cases):
    v = voice(seed=seed, seconds=30, sibilance=0.8)
    centred = measure_vocal(v, FS)
    assert centred.sibilant_share > 0.02 and centred.sibilant_peak_hz
    for how in cases:
        m = measure_vocal(_widened(v, how), FS)
        plan = _plan(m, "double")
        # the old mono fold lost nearly every 's' (share 0.000–0.003, no peak, band back to 4.5 kHz)
        assert m.sibilant_share > 0.6 * centred.sibilant_share, how
        assert m.sibilant_peak_hz and _octaves(m.sibilant_peak_hz, centred.sibilant_peak_hz) < 0.35, how
        assert any(t.label.startswith("De-esser principal") for t in plan), how
        # and the comb of a 0.6–1 ms offset was read as resonances, a 0.3 ms one as low-mid build-up
        assert not any(t.kind == "eq" for t in plan), (how, [t.label for t in plan])
        assert m.mud_db == pytest.approx(centred.mud_db, abs=0.5), how


def test_sibilant_frames_compare_the_power_of_each_channel():
    v = voice(seed=3, seconds=8, sibilance=0.8)
    level, active, _ = active_frames(v, FS)
    s_centred, vowels_centred = sibilant_frames(v, FS, level, active)
    x = _widened(v, "anti-phase")
    level, active, _ = active_frames(x, FS)
    s_anti, vowels_anti = sibilant_frames(x, FS, level, active)
    assert s_centred.sum() > 50 and np.array_equal(s_anti, s_centred) and np.array_equal(vowels_anti, vowels_centred)


# -- resonances and low-mid bumps, read on the sung harmonics below 2 kHz ------------------------

@pytest.mark.parametrize("freq", [300, 500, 800, 1200])
@pytest.mark.parametrize("seed", [3, 4])
def test_a_room_resonance_below_2khz_is_found(freq, seed):
    m = measure_vocal(voice(seed=seed, resonance_hz=freq), FS)  # +10 dB, Q 12
    assert any(_octaves(r.freq_hz, freq) <= 1 / 12 for r in m.resonances), m.resonances
    cuts = [t for t in _plan(m) if t.label.startswith("Résonance")]
    assert any(_octaves(t.params["freq_hz"], freq) <= 1 / 12 and t.params["gain_db"] < -1.5 for t in cuts)


@pytest.mark.parametrize("seed,notes", [(s, None) for s in range(1, 9)] + [(1, DEEP), (3, DEEP)])
def test_a_clean_voice_gets_no_eq_cut(seed, notes):
    m = measure_vocal(voice(seed=seed, notes=notes), FS)
    assert not m.resonances
    assert not [t.label for t in _plan(m) if t.kind == "eq"]


@pytest.mark.parametrize("seed,notes", [(3, [440, 494]), (8, [440, 494]), (3, [494, 523, 587]), (8, [415, 466])])
def test_a_high_voice_gets_no_cut_at_its_own_pitch(seed, notes):
    m = measure_vocal(voice(seed=seed, notes=notes), FS)
    assert not [t.label for t in _plan(m) if t.kind == "eq"]


@pytest.mark.parametrize("seed", [3, 5])
def test_a_broad_low_mid_bump_arms_the_low_mid_cut(seed):
    m = measure_vocal(apply_sos(voice(seed=seed), peaking_sos(FS, 300, 2.0, 6.0)), FS)
    cut = [t for t in _plan(m) if t.label.startswith("Bas-médiums")]
    assert cut and _octaves(cut[0].params["freq_hz"], 300) <= 1 / 6 and m.low_mid_excess_db >= LOW_MID_MIN_DB
    assert f"{m.low_mid_excess_db:.1f} dB" in cut[0].reason


@pytest.mark.parametrize("seed", [1, 5])
def test_no_low_mid_bump_is_placed_where_no_harmonic_was_measured(seed):
    centres = 75.0 * 2 ** ((np.arange(103) + 0.5) / 24)
    counts = np.where(centres > 520, 40.0, 0.0)  # harmonics from 527 Hz up only (2nd harmonic of 262 Hz)
    lift = np.where(np.abs(np.log2(centres / 527)) < 1 / 30, 4.0, 0.0)
    note = HarmonicProfile(centres, lift * counts, counts, np.where(lift > 0, counts, 0.0))
    assert low_mid_buildup(note, [note, note], []) == (300.0, 0.0, 0)  # even when two notes show it
    # a clean voice on 262–440 Hz, a little warm: its 2nd harmonics sit on the vowels' first formant,
    # and the 1/3-octave average of the 524 Hz one alone read as a 2.6 dB bump at 469 Hz, cut by 3 dB
    x = apply_sos(voice(seed=seed, notes=[262, 294, 330, 349, 392, 440]), shelf_sos(FS, 300, 3.0, high=False))
    m = measure_vocal(x, FS)
    assert m.mud_db > 6.0 and not [t.label for t in _plan(m) if t.kind == "eq"]


def _measure(**kw):
    base = dict(loudness_lufs=-20.0, mud_db=8.0, low_mid_hz=310.0, low_mid_excess_db=3.0)
    return VocalMeasure(**{**base, **kw})


def test_no_low_mid_cut_next_to_a_resonance_cut():
    def low_mid(m):
        return [t for t in _plan(m) if t.label.startswith("Bas-médiums")]
    assert low_mid(_measure())
    assert not low_mid(_measure(resonances=[Resonance(300.0, 6.0)]))  # the resonance cut acts there already
    assert low_mid(_measure(resonances=[Resonance(620.0, 6.0)]))  # an octave away: both cuts


def _profile(bump_hz, bump_db, width_bands):
    """A flat harmonic profile (40 harmonics in each 1/24-octave band) with one bump."""
    centres = 75.0 * 2 ** ((np.arange(103) + 0.5) / 24)
    counts = np.full(centres.size, 40.0)
    lift = np.where(np.abs(np.log2(centres / bump_hz)) * 24 <= width_bands, bump_db, 0.0)
    return HarmonicProfile(centres, lift * counts, counts, np.where(lift > 0, counts, 0.0))


def test_nothing_is_cut_on_a_note_the_voice_dwells_on():
    narrow = _profile(300.0, 8.0, 1)
    no_lpc = (np.linspace(0, 8000, 64), np.zeros(64))
    found = find_resonances(narrow, no_lpc, [])
    assert len(found) == 1 and _octaves(found[0].freq_hz, 300) < 1 / 24
    assert found[0].excess_db >= RESONANCE_MIN_DB
    assert find_resonances(narrow, no_lpc, [150.0]) == []  # its 2nd harmonic
    assert find_resonances(narrow, no_lpc, [290.0]) == []  # the note itself
    broad = _profile(300.0, 4.0, 6)
    two_notes = [broad, broad]  # each sung note shows the bump on its own
    assert low_mid_buildup(broad, two_notes, [])[1] == pytest.approx(4.0)
    assert _octaves(low_mid_buildup(broad, two_notes, [])[0], 300) < 1 / 12
    assert low_mid_buildup(broad, two_notes, [300.0])[1] < 4.0
    # a broad lift (a vowel formant spreads like this) is not a narrow resonance
    assert find_resonances(_profile(600.0, 6.0, 8), no_lpc, []) == []


def test_frequent_notes():
    pitches = np.concatenate([np.full(40, 440.0), np.full(30, 494.0), np.full(30, 262.0), np.full(10, np.nan)])
    assert [round(p) for p in frequent_pitches(pitches)] == [440]  # 40 % > 30 %, the others 30 % and under
    assert FREQUENT_NOTE_SHARE == 0.3
    assert near_sung_notes(880 * 2 ** (1 / 7), [440.0]) and not near_sung_notes(880 * 2 ** (1 / 5), [440.0])


# -- phrases: the 400 ms loudness blocks are placed in samples at every sample rate -------------

def _gated(seconds, seed=11):
    v = voice(seed=seed, phrase_spread_db=4, seconds=seconds)[:, 0]
    t = np.arange(v.size) / FS
    return np.stack([v * ((t % 1.95) < 1.6)] * 2, axis=1)  # 1.6 s lines, 0.35 s rests


def _spread(x, fs):
    _, active, size = active_frames(x, fs)
    blocks = block_loudness(x, fs)
    lufs = gated_loudness(blocks)
    sung = blocks[np.isfinite(blocks) & (blocks > lufs - 10) & _inside_phrases(active, size, fs, blocks.size)]
    return np.percentile(sung, 90) - np.percentile(sung, 10)


def test_phrase_blocks_do_not_drift_at_44k():
    x = _gated(210)
    # counted in 1 ms frames of 44 samples, the blocks slid 0.5 s late by the end: 4.31 dB at 44.1 kHz vs 3.29
    assert _spread(x, 44100.0) == pytest.approx(_spread(resample_poly(x, 160, 147, axis=0), 48000.0), abs=0.2)


# -- de-essers: the trigger, the depth and the threshold measure the same thing ---------------------

def test_sibilant_excess_is_read_in_the_deessers_band():
    x = voice(seed=6, sibilance=1.2)
    m = measure_vocal(x, FS)
    level, active, size = active_frames(x, FS)
    s_frames, _ = sibilant_frames(x, FS, level, active)
    low = deess_band_low_hz(sibilant_peak(x, FS, s_frames, size))
    band, _ = dsp.band_levels_db(dsp.split_band(x, FS, low, None)[0], FS)
    assert m.sibilant_excess_db == pytest.approx(np.percentile(band[s_frames], 90)
                                                 - vowel_level(x, FS, level, active))
    deessers = [t for t in _plan(m) if t.kind == "deesser"]
    assert len(deessers) == 2 and all(t.params["low_hz"] == low for t in deessers)
    assert deess_band_low_hz(None) == 4500.0 and deess_band_low_hz(20000.0) == 8000.0
    assert deess_band_low_hz(7000.0) == pytest.approx(4900.0)


@pytest.mark.parametrize("seed,spread,sibilance", [(7, 16, 0.3), (6, 16, 0.3), (6, 4, 0.7), (7, 4, 0.7), (5, 4, 1.0)])
def test_a_planned_deesser_is_never_idle(seed, spread, sibilance):
    x = voice(seed=seed, phrase_spread_db=spread, sibilance=sibilance)
    plan = _plan(measure_vocal(x, FS))
    apply(x, FS, plan)
    # (7, 16, 0.3) used to plan a main de-esser that then reduced nothing
    assert all(t.applied for t in plan if t.kind == "deesser"), [(t.label, t.measured) for t in plan]


# -- high-pass: decided an octave under the planned cut, not on the voice's own fundamental --------

@pytest.mark.parametrize("notes", [None, DEEP, [131, 147, 165]])
def test_a_clean_voice_is_not_high_passed_for_its_own_fundamental(notes):
    m = measure_vocal(voice(seed=3, notes=notes), FS)
    for role in ("lead_vocal", "double", "adlib", "back_vocal"):
        assert not [t for t in _plan(m, role) if t.kind == "highpass"], role


@pytest.mark.parametrize("samples", [44, 60, 88, 200])
def test_a_voice_of_a_few_milliseconds_is_measured(samples):
    # decimated for the low spectrum, 44 to 87 samples leave a single sample to analyse
    m = measure_vocal(voice(seed=3, seconds=1)[:samples], FS)
    assert not [t for t in _plan(m) if t.kind == "highpass"]


@pytest.mark.parametrize("seed,notes", [(3, None), (5, None), (3, DEEP)])
def test_rumble_is_high_passed_and_the_reason_states_the_measure(seed, notes):
    m = measure_vocal(voice(seed=seed, notes=notes, rumble=0.04), FS)
    for role in ("lead_vocal", "double"):
        hp = min(PROFILES[role].highpass_hz, 0.9 * m.lowest_f0_hz)
        cut = [t for t in _plan(m, role) if t.kind == "highpass"]
        lows = m.energy_below_db(hp / 2)
        assert lows > HIGHPASS_TRIGGER_DB and cut and cut[0].params["freq_hz"] == pytest.approx(hp)
        assert f"{lows:.0f} dB de l'énergie de la voix sous {hp / 2:.0f} Hz" in cut[0].reason


# -- the plan does not depend on how loud the voice was rendered -----------------------------------

def test_the_same_voice_rendered_quieter_gets_the_same_plan():
    base = voice(seed=11, phrase_spread_db=8, sibilance=0.7, seconds=30)
    base = base / np.max(np.abs(base))
    plans = []
    for peak_db in (-1.0, -30.0, -40.0):
        x = base * 10 ** (peak_db / 20)
        m = measure_vocal(x, FS)
        sung = active_frames(x, FS)[1].mean()
        plans.append((round(sung, 3), round(m.dynamic_spread_db, 2), [t.label for t in _plan(m, "adlib")]))
    # with a −60 dB floor the −30 dB render lost its quiet syllables and its light de-esser,
    # the −35 dB one its spread (3.7 → 1.2 dB)
    assert plans[0] == plans[1] == plans[2]
    assert SILENCE_DB == -90.0


# -- masking bands: same powers as a whole-song STFT, a few seconds at a time --------------------------

def _whole_song_band_power(x, fs, mask, edges):
    two_d = x if x.ndim == 2 else x[:, None]
    freqs, times, z = stft(two_d, fs=fs, nperseg=4096, noverlap=3072, axis=0, boundary=None)
    power = np.sum(np.abs(z) ** 2, axis=1)
    block = np.clip(np.round((times - 0.2) / 0.1).astype(int), 0, max(mask.size - 1, 0))
    mean = power[:, mask[block]].mean(axis=1)
    return np.array([mean[(freqs >= lo) & (freqs < hi)].sum() for lo, hi in edges])


def test_masking_band_power_is_unchanged_and_needs_little_memory():
    rng = np.random.default_rng(0)
    n = 60 * FS
    x = rng.standard_normal((n, 2)) * ((np.arange(n) // FS) % 5 < 4)[:, None]
    mask = level_of(x, FS).active_blocks
    edges = [(250 * 2 ** (k / 3 - 1 / 6), 250 * 2 ** (k / 3 + 1 / 6)) for k in range(16)]
    for sig in (x, x[:, 0]):
        assert _band_power(sig, FS, mask, edges) == pytest.approx(_whole_song_band_power(sig, FS, mask, edges),
                                                                  rel=1e-5)
    tracemalloc.start()
    _band_power(x, FS, mask, edges)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert peak < 40e6  # the whole-song stereo STFT of this minute alone held about 170 MB


# -- docs/mixage.md tells what the code does -------------------------------------------------------------

def _french(value):
    return f"{value:g}".replace(".", ",").replace("-", "−")


def test_the_voice_chain_section_of_the_docs_matches_the_code():
    doc = Path(__file__).resolve().parent.parent / "docs" / "mixage.md"
    section = doc.read_text(encoding="utf-8").split("## 2. ")[1].split("## 3. ")[0]
    ratios = []
    for spread in (4.01, 6.0, 10.0, 20.0):
        comp = next(t for t in _plan(_measure(dynamic_spread_db=spread)) if t.label.startswith("Compression de niveau"))
        ratios.append(comp.params["ratio"])
    assert ratios[0] == pytest.approx(1.5, abs=0.01) and ratios[2] == ratios[3] == 3.0
    leveling = next(line for line in section.splitlines() if line.startswith("| Compression de niveau"))
    assert "1,5:1 (écart de 4 dB) à 3:1 (10 dB et plus)" in leveling
    prose = section.replace("\n", " ")
    assert "facteur de crête > 9 dB), la compression des crêtes, et au-delà de 12 dB" in prose
    assert "le gain de compensation suit dès qu'un compresseur ou un de-esser a agi" in prose
    assert not re.search(r"^>", section, re.MULTILINE)  # a line opening on '>' would render as a quote
    for value in (HIGHPASS_TRIGGER_DB, RESONANCE_MIN_DB, LOW_MID_MIN_DB):
        assert f"{_french(value)} dB" in section, value
    assert f"{FREQUENT_NOTE_SHARE * 100:.0f} %" in section and f"{_french(SILENCE_DB)} dBFS" in section
