"""Mix engine, fifth review round: another voice may keep its level, follow the lead's own static change or
anything between, and out of its window moves towards its goal at most 4 dB beyond that span (a copy of
the lead is never raised against it); a voice left as it is while the lead moves says so."""

import functools

import pytest

from eden.mix.engine import MAX_LEVEL_CHANGE_DB, mix
from eden.mix.loudness import integrated_loudness
from synth_voice import FS, beat, voice
from test_engine_mix import _against, _gain_db, _parts

SECONDS = 16.0
COMB = "elle le suit, pas plus : copie de la voix principale, la monter davantage créerait un filtrage en peigne"


def _under(x, lead, relative_db):
    """``x`` set ``relative_db`` LU from ``lead``."""
    return x * 10 ** ((relative_db - integrated_loudness(x, FS) + integrated_loudness(lead, FS)) / 20)


@functools.cache
def _stack(lead_balance_db: float, double_db: float, double_is_copy: bool = False):
    """A lead ``lead_balance_db`` against the beat, a double ``double_db`` LU from it (a copy of the lead
    or another take) and ad-libs 6 LU under it: the balance inside the stack is the user's."""
    instru = beat(SECONDS)
    lead = _against(voice(SECONDS, seed=11), instru, lead_balance_db)
    double = _under(lead if double_is_copy else voice(SECONDS, seed=13), lead, double_db)
    adlibs = _under(voice(SECONDS, seed=17), lead, -6.0)
    parts = _parts([("ch0", "Lead", "lead_vocal", lead, None), ("ch1", "Double", "double", double, None),
                    ("ch2", "Ad-libs", "adlib", adlibs, None)], [("g1", "Instru", "beat", instru)])
    out = mix(parts, 1.0, 95.0, {"ch0": "none", "ch1": "none", "ch2": "none"})
    return {p.key: p for p in out.parts}, out.warnings


def _reason(result) -> str:
    return next(t.reason for t in result.treatments if t.kind == "gain")


@pytest.mark.parametrize("lead_balance_db", [-8.0, 10.0], ids=["rendered low", "rendered loud"])
def test_a_stack_inside_its_windows_moves_as_a_whole_and_keeps_its_balance(lead_balance_db):
    res, warnings = _stack(lead_balance_db, -6.0)
    lead = res["ch0"].level_change_db
    assert abs(lead) > MAX_LEVEL_CHANGE_DB  # more than the others could move on their own
    for key in ("ch1", "ch2"):
        assert res[key].level_change_db == pytest.approx(lead, abs=1e-9)
        assert -10.0 < res[key].loudness_after - res["ch0"].loudness_after < -3.0
        assert _reason(res[key]).endswith(f"dB par rapport à « Lead » si elle suivait son gain ({lead:+.1f} dB)")
    assert not [w for w in warnings if "« Double »" in w or "« Ad-libs »" in w]


def test_a_voice_too_quiet_once_it_follows_moves_at_most_4_db_beyond_following():
    res, _ = _stack(-8.0, -14.0)
    assert res["ch1"].level_change_db == pytest.approx(res["ch0"].level_change_db + MAX_LEVEL_CHANGE_DB, abs=1e-9)


def test_a_voice_still_off_its_window_after_following_and_4_db_more_is_named():
    res, warnings = _stack(-8.0, -16.0)
    assert res["ch1"].level_change_db == pytest.approx(res["ch0"].level_change_db + MAX_LEVEL_CHANGE_DB, abs=1e-9)
    final = res["ch1"].loudness_after - res["ch0"].loudness_after
    [warning] = [w for w in warnings if "« Double »" in w]
    assert warning.startswith(f"« Double » reste à {final:+.1f} dB de « Lead »")
    assert warning.endswith("monte cette voix dans FL Studio")


def test_a_voice_a_little_too_loud_rises_only_to_its_goal_not_as_far_as_a_buried_lead():
    res, warnings = _stack(-8.0, 0.0)
    lead, double = res["ch0"].level_change_db, res["ch1"].level_change_db
    assert 0.0 < double < lead - 4.0  # the old rule left it as it was, following would leave it 6 dB too loud
    assert res["ch1"].loudness_after - res["ch0"].loudness_after == pytest.approx(-6.0, abs=1e-9)  # its goal
    assert not [w for w in warnings if "« Double »" in w]


def test_a_voice_far_too_loud_is_lowered_even_with_a_buried_lead():
    res, warnings = _stack(-8.0, 8.0)
    lead = res["ch0"].level_change_db
    assert lead > MAX_LEVEL_CHANGE_DB
    # following would leave it 8 dB over the lead: it may go from keeping its level down 4 dB more
    assert res["ch1"].level_change_db == pytest.approx(-MAX_LEVEL_CHANGE_DB, abs=1e-9)
    assert -10.0 < res["ch1"].loudness_after - res["ch0"].loudness_after < -3.0
    assert not [w for w in warnings if "« Double »" in w]


def test_a_voice_that_stays_as_it_is_while_the_lead_moves_says_so():
    # set where keeping its level puts it on its goal: from a first mix, its own change is taken back
    first, _ = _stack(-8.0, 0.0)
    res, _ = _stack(-8.0, first["ch1"].level_change_db)
    kept = next(t for t in res["ch1"].treatments if t.kind == "gain")
    assert res["ch1"].level_change_db == 0 and kept.label == "Niveau gardé"
    assert kept.reason.startswith("Équilibre : ") and kept.reason.endswith(
        f"par rapport à « Lead » si elle suivait son gain ({res['ch0'].level_change_db:+.1f} dB)")


def test_a_copy_of_the_lead_follows_its_gain_but_is_never_raised_against_it():
    res, warnings = _stack(-8.0, -14.0, True)
    lead = res["ch0"].level_change_db
    assert lead > MAX_LEVEL_CHANGE_DB
    assert res["ch1"].level_change_db == pytest.approx(lead, abs=1e-9)
    kept = next(t for t in res["ch1"].treatments if t.kind == "gain")
    assert kept.label == f"Niveau {lead:+.1f} dB"
    assert kept.reason.endswith(f"si elle suivait son gain ({lead:+.1f} dB) ; {COMB}")
    assert not [w for w in warnings if "« Double »" in w]


def test_a_copy_of_a_lead_left_as_it_is_is_kept_at_its_level():
    res, _ = _stack(1.0, -14.0, True)
    assert _gain_db(res["ch0"]) == 0
    kept = next(t for t in res["ch1"].treatments if t.kind == "gain")
    assert kept.label == "Niveau gardé" and res["ch1"].level_change_db == 0
