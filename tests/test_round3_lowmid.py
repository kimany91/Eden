"""A voice's low-mid cut, round 3: a bump counts only when two sung notes show it on their own, every
time, so the vowels' formant on a high voice's lowest notes is no longer cut."""

import math
from pathlib import Path

import numpy as np
import pytest
from scipy.signal import resample_poly, sosfreqz

from eden.mix.analysis import (LOW_MID_MIN_DB, LOW_MID_STEADY_SHARE, MIN_SAMPLES, THIRD, HarmonicProfile,
                               active_frames, frame_pitches, harmonic_profile, low_mid_buildup, measure_vocal,
                               note_groups, note_profiles, pitch_frames, sung_samples)
from eden.mix.dsp import apply_sos, peaking_sos, shelf_sos
from eden.mix.vocal import plan_voice
from synth_voice import FS, voice

CENTRES = 75.0 * 2 ** ((np.arange(103) + 0.5) / 24)  # the profile's 1/24-octave bands


def _low_mid_cut(m):
    return [t for t in plan_voice(m, "lead_vocal", 1.0, False) if t.label.startswith("Bas-médiums")]


# -- notes: the pitched frames grouped by the semitone-wide span that holds the most ------------------------

def _sung(*notes, frames=60):
    """``frames`` pitches per note, with a ±0.4 % vibrato (like the test voices)."""
    wobble = 1 + 0.004 * np.sin(2 * np.pi * np.arange(frames) / 7)
    return np.concatenate([note * wobble for note in notes])


def test_a_note_sung_between_two_semitones_stays_one_note():
    pitches = _sung(240.0, 270.0)
    # 240 Hz lies 49 cents under B3: rounded to the nearest semitone, its vibrato makes two notes
    assert np.unique(np.round(12 * np.log2(pitches[:60] / 440.0))).size == 2
    labels = note_groups(pitches)
    assert np.unique(labels[:60]).size == 1 and np.unique(labels[60:]).size == 1 and labels[0] != labels[60]


def test_notes_a_semitone_apart_are_two_notes_and_frames_without_pitch_none():
    pitches = np.concatenate([_sung(247.0, frames=40), _sung(262.0, frames=70), [np.nan] * 5])
    labels = note_groups(pitches)
    assert set(labels[:40]) == {1} and set(labels[40:110]) == {0}  # the note holding the most frames first
    assert (labels[110:] == -1).all()
    assert note_groups(np.full(4, np.nan)).tolist() == [-1] * 4 and note_groups(np.zeros(0)).size == 0


def test_each_note_profile_holds_the_harmonics_of_its_own_frames():
    x = voice(seed=3, seconds=8, notes=[247, 277, 330])
    _, active, size = active_frames(x, FS)
    frames = pitch_frames(sung_samples(x, active, size), FS)
    pitches = frame_pitches(frames, FS)
    per_note = note_profiles(frames, pitches, FS)
    whole = harmonic_profile(frames, pitches, FS)
    assert len(per_note) >= 3
    # every pitched frame is in one note: the notes add up to the whole voice
    for field in ("sums", "counts", "lifted"):
        assert np.allclose(sum(getattr(p, field) for p in per_note), getattr(whole, field))


# -- the rule, on profiles built by hand ---------------------------------------------------------------------

def _note(lift_db, share=1.0, count=40.0, at=300.0):
    """One note's profile: ``count`` harmonics in every band; within 1/4 octave of ``at`` they are lifted
    by ``lift_db`` on average and stand above their neighbours' line in ``share`` of the cases."""
    inside = np.abs(np.log2(CENTRES / at)) <= 1 / 4
    counts = np.full(CENTRES.size, count)
    return HarmonicProfile(CENTRES, np.where(inside, lift_db, 0.0) * counts, counts,
                           np.where(inside, share, 0.0) * counts)


def _voice_of(*notes):
    return HarmonicProfile(CENTRES, sum(n.sums for n in notes), sum(n.counts for n in notes),
                           sum(n.lifted for n in notes))


def _buildup(*notes):
    return low_mid_buildup(_voice_of(*notes), list(notes), [])


def test_a_bump_on_a_single_note_is_no_bump():
    assert _buildup(_note(6.0), _note(0.0, share=0.5)) == (300.0, 0.0, 0)
    assert _buildup(_note(6.0)) == (300.0, 0.0, 0)


def test_a_bump_on_two_notes_reports_the_lift_of_every_note_pooled():
    hz, excess, notes = _buildup(_note(4.0), _note(2.0), _note(0.0, share=0.5))
    assert abs(math.log2(hz / 300.0)) <= 1 / 16 and notes == 2
    assert excess == pytest.approx(2.0)  # (4 + 2 + 0) / 3: the pooled lift, not the two notes' own
    assert _buildup(_note(4.0), _note(3.0), _note(3.5))[1:] == (pytest.approx(3.5), 3)


def test_each_of_the_two_notes_must_lift_enough_every_time_on_enough_harmonics():
    enough = LOW_MID_MIN_DB - 1
    assert _buildup(_note(4.0), _note(enough + 0.05))[2] == 2
    assert _buildup(_note(4.0), _note(enough - 0.05)) == (300.0, 0.0, 0)
    # lifted on average, but above the line in only 80 % of the cases: a formant passing, not a bump
    assert _buildup(_note(4.0), _note(3.0, share=LOW_MID_STEADY_SHARE + 0.02))[2] == 2
    assert _buildup(_note(4.0), _note(3.0, share=0.8)) == (300.0, 0.0, 0)
    # a note with fewer than MIN_SAMPLES harmonics over the 1/3 octave is not judged
    few = (MIN_SAMPLES - 1) / THIRD.sum()
    assert _buildup(_note(4.0), _note(4.0, count=few)) == (300.0, 0.0, 0)
    assert _buildup(_note(4.0), _note(4.0, count=MIN_SAMPLES / THIRD.sum()))[2] == 2


# -- on the test voices --------------------------------------------------------------------------------------

def _warm(notes, seed, shelf_db):
    x = voice(seed=seed, notes=notes)
    return apply_sos(x, shelf_sos(FS, 300, shelf_db, high=False)) if shelf_db else x


F240, F245, F247, F250 = [240, 270, 300, 320, 360], [245, 275, 310, 330, 367], [247, 277, 311, 330, 370], \
    [250, 280, 315, 335, 375]


# clean voices whose lowest notes are 220–250 Hz: the eight cut before (seed 11, 3.0 to 3.6 dB on every note
# pooled) and the highest other readings (seed 2: 2.3 to 2.9 dB)
@pytest.mark.parametrize("notes,seed,shelf_db,muddy", [
    (F240, 11, 1.4, True), (F245, 11, 1.4, True), (F245, 11, 2.0, True), (F245, 11, 3.0, True),
    (F247, 11, 1.4, True), (F247, 11, 2.0, True), (F247, 11, 3.0, True), (F250, 11, 3.0, True),
    (F247, 2, 1.4, True), (F240, 2, 1.4, True), (F250, 2, 3.0, True), ([220, 247, 262, 294, 330], 2, 0.0, True),
    ([233, 262, 294, 330, 349, 392], 2, 0.0, False),
])
def test_a_clean_voice_whose_lowest_notes_are_220_to_250_hz_gets_no_low_mid_cut(notes, seed, shelf_db, muddy):
    m = measure_vocal(_warm(notes, seed, shelf_db), FS)
    assert m.low_mid_notes == 0 and m.low_mid_excess_db == 0.0
    assert not _low_mid_cut(m)
    assert (m.mud_db > 6.0) == muddy  # muddy: the other trigger is met, the bump measure alone keeps the cut out


def _profiles(x, fs):
    _, active, size = active_frames(x, fs)
    sung = sung_samples(x, active, size)
    frames = pitch_frames(sung, fs)
    pitches = frame_pitches(frames, fs)
    return harmonic_profile(frames, pitches, fs), note_profiles(frames, pitches, fs)


def test_the_vowels_formant_lifts_two_notes_only_part_of_the_time():
    # seed 11, lowest note 247 Hz, +1.4 dB under 300 Hz: every note pooled, the harmonics just under 500 Hz
    # stand 3.4 dB above their neighbours' line; the notes 247 and 277 Hz both lift theirs there (their
    # 2nd harmonics, 494 and 554 Hz), but only when the vowel's first formant sits on them
    whole, per_note = _profiles(_warm(F247, 11, 1.4), FS)
    band = int(np.argmin(np.abs(whole.centres - 497)))
    assert whole.mean(THIRD)[band] > LOW_MID_MIN_DB + 0.8
    with np.errstate(invalid="ignore"):
        lifting = [p for p in per_note if p.mean(THIRD)[band] >= LOW_MID_MIN_DB - 1]
    assert len(lifting) == 2
    # above their neighbours' line in 74 % and 85 % of the cases: under LOW_MID_STEADY_SHARE
    assert sorted(round(float(p.lifted_share(THIRD)[band]), 2) for p in lifting) == [0.74, 0.85]


def _bump(freq, q, seed, fs=FS):
    x = apply_sos(voice(seed=seed), peaking_sos(FS, freq, q, 6.0))
    return x if fs == FS else resample_poly(x, fs // 300, FS // 300, axis=0)


def _bump_gain_db(freq, q, at_hz):
    _, h = sosfreqz(peaking_sos(FS, freq, q, 6.0), worN=[at_hz], fs=FS)
    return 20 * math.log10(abs(h[0]))


# +6 dB bumps: on each, the seed of 1–8 where it reads lowest, and seed 11
@pytest.mark.parametrize("freq,q,seed", [(300, 2.0, 5), (300, 4.0, 7), (200, 2.0, 1), (400, 2.0, 4),
                                         (300, 2.0, 11), (300, 4.0, 11), (200, 2.0, 11), (400, 2.0, 11)])
def test_the_acceptance_bumps_are_still_cut_where_they_are(freq, q, seed):
    m = measure_vocal(_bump(freq, q, seed), FS)
    assert m.low_mid_excess_db >= LOW_MID_MIN_DB + 0.4 and m.low_mid_notes >= 2
    cut = _low_mid_cut(m)
    assert cut
    # where the cut sits, the bump lifts the voice by more than half its 6 dB
    assert _bump_gain_db(freq, q, cut[0].params["freq_hz"]) > 3.0
    if (freq, seed) != (400, 11):  # see the next test
        assert abs(math.log2(cut[0].params["freq_hz"] / freq)) <= 1 / 6
    reason = cut[0].reason
    assert f"{m.low_mid_notes} notes chantées la portent chacune" in reason
    assert f"au moins {LOW_MID_MIN_DB - 1:.1f} dB" in reason
    assert f"{LOW_MID_STEADY_SHARE * 100:.0f} % des cas" in reason


def test_seed_11_reads_its_400_hz_bump_at_456_hz():
    # what the docs say: on this seed the strongest 1/3 octave lies 0.19 octave above the bump's centre,
    # where the bump still lifts 4.7 dB, and the cut there still takes 91 % of its depth at 400 Hz
    m = measure_vocal(_bump(400, 2.0, 11), FS)
    cut = _low_mid_cut(m)[0].params
    assert round(m.low_mid_hz) == 456 and _bump_gain_db(400, 2.0, m.low_mid_hz) > 4.6
    _, h = sosfreqz(peaking_sos(FS, cut["freq_hz"], cut["q"], cut["gain_db"]), worN=[400.0], fs=FS)
    assert 20 * math.log10(abs(h[0])) < 0.9 * cut["gain_db"]


def test_the_rule_holds_at_48_khz():
    assert not _low_mid_cut(measure_vocal(resample_poly(_warm(F247, 11, 1.4), 160, 147, axis=0), 48000))
    m = measure_vocal(_bump(300, 2.0, 5, 48000), 48000)
    assert _low_mid_cut(m) and abs(math.log2(m.low_mid_hz / 300)) <= 1 / 6


# -- docs/mixage.md tells what the code does -----------------------------------------------------------------

def _french(value):
    return f"{value:g}".replace(".", ",")


def test_the_docs_state_the_two_note_rule():
    doc = (Path(__file__).resolve().parent.parent / "docs" / "mixage.md").read_text(encoding="utf-8")
    row = next(line for line in doc.split("## 2. ")[1].split("## 3. ")[0].splitlines()
               if line.startswith("| Bas-médiums"))
    assert f"bosse ≥ {_french(LOW_MID_MIN_DB)} dB" in row
    assert "deux notes" in row and f"{_french(LOW_MID_MIN_DB - 1)} dB" in row
    assert f"{LOW_MID_STEADY_SHARE * 100:.0f} %" in row
    assert "une seule note" in row and "456 Hz" in row
    assert "c'est la mesure qu'il faudrait revoir" not in row
