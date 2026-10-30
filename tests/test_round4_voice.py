"""A voice's chain and its building blocks, round 4: the make-up follows only a compressor or a de-esser
that acted, the light de-esser shows its real maximum, the module texts say what the code does, and the
product keeps no function or field that only the tests use."""

import ast
import functools
import inspect
import math
from pathlib import Path

import numpy as np
import pytest

from eden.mix import analysis, master, stereo, vocal
from eden.mix.analysis import VocalMeasure, measure_vocal
from eden.mix.engine import _chain
from eden.mix.loudness import integrated_loudness
from eden.mix.parts import Part, split
from eden.mix.treatments import Treatment, apply
from eden.mix.vocal import plan_voice
from eden.project.inspector import inspect_project
from eden.project.sources import SearchRoots
from eden.render.pipeline import render_project
from synth_voice import FS, voice
from test_round2_voice import _echo
from test_render import make_session, sim_renderer

SRC = Path(__file__).resolve().parent.parent / "src" / "eden"


# -- the make-up gives back level only after a compressor or a de-esser took some ----------------------------

def _compressor(threshold_db):
    return Treatment("compressor", "Compression", "test", {"threshold_db": threshold_db, "ratio": 4.0,
                                                           "attack_ms": 5.0, "release_ms": 100.0})


def _makeup():
    return Treatment("makeup", "Gain de compensation", "test")


def test_the_make_up_follows_only_a_compressor_or_a_deesser_that_acted():
    x = voice(seconds=8, seed=3)
    cut = Treatment("eq", "EQ", "test", {"freq_hz": 1000.0, "q": 0.7, "gain_db": -6.0})
    idle, makeup = _compressor(0.0), _makeup()
    out = apply(x, FS, [cut, idle, makeup])
    # the cut lowered the voice, but no dynamic stage acted: nothing is given back
    assert not idle.applied and not makeup.applied and makeup.params == {}
    assert np.array_equal(out, apply(x, FS, [cut]))
    assert integrated_loudness(out, FS) < integrated_loudness(x, FS) - 1.0
    makeup = _makeup()
    assert np.array_equal(apply(x, FS, [makeup]), x) and not makeup.applied
    working, makeup = _compressor(-40.0), _makeup()
    out = apply(x, FS, [cut, working, makeup])
    assert working.applied and makeup.applied and makeup.params["gain_db"] > 10.0
    assert integrated_loudness(out, FS) == pytest.approx(integrated_loudness(x, FS), abs=0.05)
    # a de-esser that acted is enough
    sibilant = voice(seconds=8, seed=6, sibilance=1.5)
    chain = [t for t in plan_voice(measure_vocal(sibilant, FS), "lead_vocal", 1.0, False)
             if t.kind in ("deesser", "makeup")]
    apply(sibilant, FS, chain)
    assert [t.kind for t in chain] == ["deesser", "deesser", "makeup"] and all(t.applied for t in chain)


def test_a_voice_whose_compressor_stays_idle_shows_no_make_up():
    # a pre-limited voice whose FL echo (1/4 at −6 dB, 140 BPM) fills the rests: its tail-safe leveling
    # stage would only lower the level, so it is not applied; the make-up still showed +0.1 dB, which the
    # saturation alone had taken
    dry = voice(seconds=40, seed=1, phrase_spread_db=8, sibilance=0.1)
    dry = np.tanh(6.0 * dry / np.max(np.abs(dry))) * 0.2
    x = dry + _echo(dry, 60 / 140, -6.0)
    planned = plan_voice(measure_vocal(x, FS), "lead_vocal", 1.0, True)
    assert [t.kind for t in planned] == ["compressor", "saturation", "makeup"]
    _, _, _, result = _chain(Part("ch1", "Lead", "lead_vocal", x), FS, 1.0, "untracked", 140.0)
    assert [t.kind for t in result.treatments] == ["saturation"]


def test_the_make_up_reason_and_the_docs_say_when_it_acts():
    m = VocalMeasure(loudness_lufs=-20.0, mud_db=0.0, crest_db=10.0)
    makeup = plan_voice(m, "lead_vocal", 1.0, False)[-1]
    assert makeup.kind == "makeup" and makeup.reason.startswith("Un compresseur ou un de-esser a agi : ")
    doc = (SRC.parent.parent / "docs" / "mixage.md").read_text(encoding="utf-8")
    row = next(line for line in doc.split("## 2. ")[1].splitlines() if line.startswith("| Gain de compensation"))
    assert "dès qu'un compresseur ou un de-esser agit (s'ils restent tous inactifs, aucun gain" in row


# -- the light de-esser shows the maximum it is given ------------------------------------------------------------

@pytest.mark.parametrize("k,shown", [(0.1, "0.3"), (0.25, "0.8"), (0.5, "1.5"), (0.75, "2.2"), (0.85, "2.5"),
                                     (1.0, "3.0")])
def test_the_light_deesser_label_shows_its_maximum_to_a_tenth_of_a_db(k, shown):
    m = VocalMeasure(loudness_lufs=-20.0, mud_db=0.0, sibilant_excess_db=0.0)
    light = next(t for t in plan_voice(m, "lead_vocal", k, False) if t.label.startswith("De-esser léger"))
    assert light.label == f"De-esser léger (max {shown} dB)"
    assert f"{light.params['max_reduction_db']:.1f}" == shown  # the maximum the stage is given


# -- the module texts describe the chain, the measure and the keys as they are ----------------------------------

def test_the_module_texts_say_what_the_code_does(tmp_path):
    chain = " ".join(vocal.__doc__.split())
    assert "presence" not in chain
    assert "saturation → air / push-back of secondary voices → main de-esser → make-up" in chain
    assert "that dry render" in " ".join(analysis.__doc__.split())
    # the groups are keyed by their render job's name, as the field's comment says
    project = make_session(tmp_path)
    report = inspect_project(project, roots=SearchRoots())
    split_parts = split(report, render_project(project, sim_renderer(), timeout_s=120, report=report))
    assert split_parts.groups and all(g.key.startswith("stem-") for g in split_parts.groups)
    assert all(v.key == f"ch{v.channels[0]}" for v in split_parts.voices)
    assert '"ch<index>" for a voice, the render job\'s name ("stem-…") for a group' in inspect.getsource(Part)


# -- the product keeps no function, constant or field that only the tests use -----------------------------------

@functools.cache
def _product() -> tuple[tuple[Path, ast.Module], ...]:
    return tuple((path, ast.parse(path.read_text(encoding="utf-8"))) for path in SRC.rglob("*.py"))


def _uses_of(module: str) -> set[str]:
    """The names of ``eden.mix.<module>`` the product reads: imported from it, read as an attribute of the
    module, or read inside the module itself. A same-named identifier elsewhere (the engine's ``ride``,
    imported from riding, for a ``stereo.ride``; report's local ``pan`` for ``stereo.pan``) does not count."""
    used = set()
    for path, tree in _product():
        aliases = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == f"eden.mix.{module}":
                used.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module == "eden.mix":
                aliases.update(a.asname or a.name for a in node.names if a.name == module)
        inside = path == SRC / "mix" / f"{module}.py"
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
                used.add(node.attr)
            elif inside and isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                used.add(node.id)
    return used


@functools.cache
def _attributes_read() -> frozenset[str]:
    """Every attribute name the product reads, on any object (a field is matched by its name)."""
    return frozenset(node.attr for _, tree in _product() for node in ast.walk(tree)
                     if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load))


@pytest.mark.parametrize("module", ["analysis", "dsp", "parts", "riding", "space", "stereo", "tonality",
                                    "treatments", "vocal"])
def test_every_public_name_of_the_voice_modules_is_used_by_the_product(module):
    # riding.phrase_differences and steadiness_db, dsp.compress, stereo.set_width, tonality.root_note and
    # space.note_seconds were called by the tests only
    defined = []
    for node in ast.parse((SRC / "mix" / f"{module}.py").read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            defined.append(node.name)
        elif isinstance(node, ast.Assign):
            defined += [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.append(node.target.id)
    used = _uses_of(module)
    assert [name for name in defined if not name.startswith("_") and name not in used] == []


@pytest.mark.parametrize("cls", [VocalMeasure, stereo.StereoMeasure, Part], ids=lambda c: c.__name__)
def test_every_field_of_the_measures_and_parts_is_read_by_the_product(cls):
    # VocalMeasure.vowel_level_db and active_share, StereoMeasure.correlation and low_side_ratio_db were
    # filled and read by the tests only; Part.is_voice (on parts.VOCAL_ROLES) was never called
    body = ast.parse(inspect.getsource(cls)).body[0].body
    members = [item.target.id for item in body if isinstance(item, ast.AnnAssign)]
    members += [item.name for item in body if isinstance(item, ast.FunctionDef) and not item.name.startswith("__")]
    assert members and [m for m in members if m not in _attributes_read()] == []


def test_is_mono_reads_only_the_side_against_the_mid(monkeypatch):
    def no_filter(*args, **kwargs):
        raise AssertionError("is_mono filtered the whole voice")

    monkeypatch.setattr(stereo, "linkwitz_riley", no_filter)
    monkeypatch.setattr(stereo, "sosfilt", no_filter)
    rng = np.random.default_rng(0)
    mid, side = rng.normal(0, 0.1, FS), rng.normal(0, 0.1, FS)
    assert stereo.is_mono(mid)
    assert stereo.is_mono(stereo.from_mid_side(mid, side * 10 ** (-25 / 20)))
    assert not stereo.is_mono(stereo.from_mid_side(mid, side * 10 ** (-15 / 20)))
    assert not stereo.is_mono(rng.normal(0, 0.1, (FS, 2)))


def test_the_master_still_reads_the_mono_loss():
    rng = np.random.default_rng(1)
    left = rng.normal(0, 0.1, 4 * FS)
    one_side = np.stack([left, np.zeros_like(left)], axis=1)
    # (left / 2)² summed in mono against (left² + 0) / 2 in stereo: half the energy, −3 dB
    assert stereo.measure(one_side).mono_loss_db == pytest.approx(10 * math.log10(0.5))
    assert stereo.measure(np.stack([left, left], axis=1)).mono_loss_db == 0.0
    checks = master.checks(one_side, FS)
    assert checks.mono_loss_db == stereo.measure(one_side).mono_loss_db
