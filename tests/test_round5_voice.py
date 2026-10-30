"""A voice's chain, fifth review round: the make-up reuses the loudness the chain measured on the voice as it
came in, and the send's de-esser splits the voice once; both give the same sound as before."""

import numpy as np

from eden.mix import dsp, space, treatments
from eden.mix.analysis import measure_vocal
from eden.mix.engine import _chain
from eden.mix.parts import Part
from eden.mix.treatments import Treatment, apply
from synth_voice import FS, voice


def _chain_steps():
    return [Treatment("compressor", "Compression", "test", {"threshold_db": -40.0, "ratio": 4.0,
                                                            "attack_ms": 5.0, "release_ms": 100.0}),
            Treatment("makeup", "Gain de compensation", "test")]


def _counting(monkeypatch, module, name):
    calls = []
    original = getattr(module, name)

    def spy(x, *args, **kwargs):
        calls.append(x)
        return original(x, *args, **kwargs)

    monkeypatch.setattr(module, name, spy)
    return calls


def test_the_make_up_reuses_the_loudness_measured_on_the_voice_as_it_came_in(monkeypatch):
    x = voice(seconds=8, seed=3)
    measured = apply(x, FS, _chain_steps())
    calls = _counting(monkeypatch, treatments, "integrated_loudness")
    given = apply(x, FS, steps := _chain_steps(), input_lufs=measure_vocal(x, FS).loudness_lufs)
    assert np.array_equal(given, measured) and steps[1].applied
    assert len(calls) == 1 and calls[0] is not x  # only the voice as it goes out is measured


def test_the_chain_gives_the_make_up_the_loudness_it_measured(monkeypatch):
    x = voice(seconds=8, seed=3, sibilance=1.5)
    calls = _counting(monkeypatch, treatments, "integrated_loudness")
    _, _, _, result = _chain(Part("ch0", "Lead", "lead_vocal", x, [0]), FS, 1.0, "none", 95.0)
    assert any(t.kind == "makeup" for t in result.treatments)
    assert not any(c is x for c in calls)


def test_the_send_deesser_splits_the_voice_once_and_touches_only_its_high_band(monkeypatch):
    x = voice(seconds=8, seed=5, sibilance=1.5)
    calls = _counting(monkeypatch, dsp, "split_band")
    change = space._deess_send(x, FS) - x
    assert len(calls) == 1
    monkeypatch.undo()
    low_change, _ = dsp.split_band(change, FS, None, 3000)
    assert np.sum(change ** 2) > 1e-3
    assert np.sum(low_change ** 2) < 0.01 * np.sum(change ** 2)
