"""A voice's chain, fifth review round, revised: the make-up gives back only what compressors and
de-essers took — measured as the voice reaches the first of them, never as it came into the chain
(that gave back what breaths and filters removed and over-boosted the voice) — and the send's
de-esser splits the voice once."""

import numpy as np

from eden.mix import dsp, space, treatments
from eden.mix.loudness import integrated_loudness
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


def _shelf():
    return Treatment("shelf", "Recul", "test", {"freq_hz": 200.0, "gain_db": -4.0, "high": True})


def test_the_make_up_gives_back_only_what_the_dynamics_took(monkeypatch):
    x = voice(seconds=8, seed=3)
    # a shelf lowers the whole voice before the compressor: the make-up must not give that back
    # (measured from the chain's input, it also returned what breaths and filters had removed)
    calls = _counting(monkeypatch, treatments, "integrated_loudness")
    y = apply(x, FS, steps := [_shelf(), *_chain_steps()])
    assert steps[-1].applied
    # measured twice: as the voice reaches the compressor, and as it goes out — never the chain's input
    assert len(calls) == 2 and not any(c is x for c in calls)
    monkeypatch.undo()
    at_dynamics = integrated_loudness(apply(x, FS, [_shelf()]), FS)
    out = integrated_loudness(y, FS)
    assert abs(out - at_dynamics) < 0.1  # back to the level that reached the compressor...
    assert out < integrated_loudness(x, FS) - 1.5  # ...not to the input's: the shelf's cut stays


def test_the_send_deesser_splits_the_voice_once_and_touches_only_its_high_band(monkeypatch):
    x = voice(seconds=8, seed=5, sibilance=1.5)
    calls = _counting(monkeypatch, dsp, "split_band")
    change = space._deess_send(x, FS) - x
    assert len(calls) == 1
    monkeypatch.undo()
    low_change, _ = dsp.split_band(change, FS, None, 3000)
    assert np.sum(change ** 2) > 1e-3
    assert np.sum(low_change ** 2) < 0.01 * np.sum(change ** 2)
