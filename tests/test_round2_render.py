"""Round 2 review fixes: why an inactive FL effect is inactive (switched off or unheard), as the
report and the interface show it, and what it means for the dry renders."""

import os

import numpy as np
import pytest
import soundfile as sf

from eden.gui import viewmodel
from eden.project.classify import RoleGuess
from eden.project.inspector import SourceAnalysis, _effects_on, _signal_path, inspect_project
from eden.project.model import FlpProject, MixerInsert, MixerSlot, PluginInfo, Route
from eden.project.sources import SearchRoots
from eden.render.plan import plan_renders
from eden.report import _source_lines, render_markdown
from flp_builder import Chan, Clip, Insert, Slot, build_flp

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # the voice card is built without a screen
os.environ.setdefault("QT_QUICK_BACKEND", "software")
BAR = 96 * 4  # 2 s at 120 BPM
SR = 22050


def make_project(folder, inserts, voices, silent=()):
    """``voices`` = [(name, insert)], each played for 2 s from a broadband sample in syllables
    (all zeros for the names in ``silent``), plus a beat on the last insert."""
    folder.mkdir(parents=True)
    t = np.arange(int(2.0 * SR)) / SR
    rng = np.random.default_rng(5)
    channels = []
    for name, insert in voices:
        voice = 0.15 * rng.standard_normal(t.size) * np.clip(np.sin(2 * np.pi * 3 * t), 0, None)
        sf.write(folder / f"{name}.wav", 0 * voice if name in silent else voice, SR)
        channels.append(Chan(name, insert=insert, sample_path=str(folder / f"{name}.wav")))
    sf.write(folder / "Beat.wav", np.stack([0.2 * np.sin(2 * np.pi * 55 * t)] * 2, axis=1), SR)
    channels.append(Chan("Instru", insert=len(inserts) - 1, sample_path=str(folder / "Beat.wav")))
    flp = folder / "Projet.flp"
    flp.write_bytes(build_flp(channels, inserts, [Clip(i + 1, 0, BAR, channel=i) for i in range(len(channels))],
                              tempo=120))
    return flp


def _report(path):
    return inspect_project(path, roots=SearchRoots())


# -- R1: switched off or unheard -------------------------------------------------------------

def _slot(index, name, enabled=True, mix_raw=None):
    return MixerSlot(index, PluginInfo(name), enabled=enabled, mix_raw=mix_raw)


def _project():
    """Every way an effect can be inactive, and one that is heard."""
    return FlpProject(inserts=[
        MixerInsert(0, "Master", routes=[]),
        MixerInsert(1, "Lead", routes=[Route(0), Route(2), Route(3), Route(4), Route(5), Route(7)],
                    slots=[_slot(0, "Fruity parametric EQ 2"), _slot(1, "Fruity Delay 3", enabled=False),
                           _slot(2, "Fruity Reeverb 2", mix_raw=0)]),
        MixerInsert(2, "Retour coupé", enabled=False, routes=[Route(0)],
                    slots=[_slot(0, "Fruity Reeverb 2"), _slot(1, "Fruity Delay 3", enabled=False)]),
        MixerInsert(3, "Retour sans sortie", routes=[], slots=[_slot(0, "Fruity Reeverb 2")]),
        MixerInsert(4, "Vers un bus coupé", routes=[Route(6)], slots=[_slot(0, "Fruity Delay 3")]),
        MixerInsert(5, "Effets coupés", effects_enabled=False, routes=[Route(0)],
                    slots=[_slot(0, "Fruity Reeverb 2")]),
        MixerInsert(6, "Bus coupé", enabled=False, routes=[Route(0)]),
        MixerInsert(7, "Retour à zéro", volume_raw=0, routes=[Route(0)], slots=[_slot(0, "Fruity Reeverb 2")]),
    ])


def _lead(project):
    path, reaches = _signal_path(project, 1)
    return SourceAnalysis(0, "Lead", "sampler", 1, "Lead", path, reaches,
                          _effects_on(project, [i for i in path if i]), RoleGuess("lead_vocal"), 1, 0.0, 2.0)


def test_an_inactive_effect_says_whether_it_is_switched_off_or_unheard():
    effects = {(e.insert_label, e.plugin): (e.active, e.inactive_reason)
               for e in _effects_on(_project(), [1, 2, 3, 4, 5, 7])}
    assert effects == {
        ("Lead", "Fruity parametric EQ 2"): (True, None),
        ("Lead", "Fruity Delay 3"): (False, "off"),
        ("Lead", "Fruity Reeverb 2"): (False, "mix_zero"),
        ("Retour coupé", "Fruity Reeverb 2"): (False, "insert_muted"),
        ("Retour coupé", "Fruity Delay 3"): (False, "off"),  # its own switch comes first
        ("Retour sans sortie", "Fruity Reeverb 2"): (False, "no_output"),
        ("Vers un bus coupé", "Fruity Delay 3"): (False, "no_output"),
        ("Effets coupés", "Fruity Reeverb 2"): (False, "off"),
        ("Retour à zéro", "Fruity Reeverb 2"): (False, "fader_zero"),
    }


def test_the_report_names_why_an_effect_is_not_heard():
    lines = "\n".join(_source_lines(_lead(_project())))
    for shown in ("Lead / slot 1 : Fruity parametric EQ 2 [Égalisation / filtre]\n",
                  "Lead / slot 2 : Fruity Delay 3 [Delay] — désactivé",
                  "Lead / slot 3 : Fruity Reeverb 2 [Reverb] — inaudible (mix à 0 %)",
                  "Retour coupé / slot 1 : Fruity Reeverb 2 [Reverb] — inaudible (insert coupé)",
                  "Retour coupé / slot 2 : Fruity Delay 3 [Delay] — désactivé",
                  "Retour sans sortie / slot 1 : Fruity Reeverb 2 [Reverb] — inaudible (insert sans sortie "
                  "vers le Master)",
                  "Vers un bus coupé / slot 1 : Fruity Delay 3 [Delay] — inaudible (insert sans sortie "
                  "vers le Master)",
                  "Effets coupés / slot 1 : Fruity Reeverb 2 [Reverb] — désactivé",
                  "Retour à zéro / slot 1 : Fruity Reeverb 2 [Reverb] — inaudible (volume de l'insert à zéro)"):
        assert shown in lines


@pytest.mark.parametrize("reverb_insert,shown", [
    ({"enabled": False}, "inaudible (insert coupé)"),
    ({"routes": ()}, "inaudible (insert sans sortie vers le Master)"),
    ({"slots": {0: Slot("Fruity Reeverb 2", enabled=False)}}, "désactivé"),
    ({"volume": 0}, "inaudible (volume de l'insert à zéro)"),
], ids=["muted", "routed-nowhere", "switched-off", "fader-at-zero"])
def test_a_reverb_return_in_a_real_project_report(tmp_path, reverb_insert, shown):
    project = make_project(tmp_path / "Projet", [
        Insert(routes=()), Insert(name="Lead", routes=(0, 2)),
        Insert(**{"name": "Reverb", "routes": (0,), "slots": {0: Slot("Fruity Reeverb 2")}, **reverb_insert}),
        Insert(name="Instru", routes=(0,))], [("Lead", 1)])
    assert f"Reverb / slot 1 : Fruity Reeverb 2 [Reverb] — {shown}\n" in render_markdown(_report(project))


def test_the_interface_gets_why_an_effect_is_not_heard():
    effects = viewmodel.source_view(_lead(_project()))["effects"]
    assert {(e["where"], e["name"]): e["inactive"] for e in effects} == {
        ("Lead", "Fruity parametric EQ 2"): "",
        ("Lead", "Fruity Delay 3"): "désactivé",
        ("Lead", "Fruity Reeverb 2"): "inaudible (mix à 0 %)",
        ("Retour coupé", "Fruity Reeverb 2"): "inaudible (insert coupé)",
        ("Retour coupé", "Fruity Delay 3"): "désactivé",
        ("Retour sans sortie", "Fruity Reeverb 2"): "inaudible (insert sans sortie vers le Master)",
        ("Vers un bus coupé", "Fruity Delay 3"): "inaudible (insert sans sortie vers le Master)",
        ("Effets coupés", "Fruity Reeverb 2"): "désactivé",
        ("Retour à zéro", "Fruity Reeverb 2"): "inaudible (volume de l'insert à zéro)",
    }


def test_the_voice_card_tooltip_shows_why_an_effect_is_not_heard():
    QtGui = pytest.importorskip("PySide6.QtGui")
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression
    from PySide6.QtQuickControls2 import QQuickStyle

    from eden.gui.app import QML_DIR

    _app = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])
    QQuickStyle.setStyle("Basic")
    engine = QQmlEngine()
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(QML_DIR / "VoiceCard.qml")))
    card = component.createWithInitialProperties({"source": viewmodel.source_view(_lead(_project()))})
    assert card is not None, component.errors()
    tips = set()
    stack = list(card.childItems())
    while stack:
        item = stack.pop()
        stack.extend(item.childItems())
        if item.metaObject().className().startswith("Chip") and item.property("dim") is not None:
            text, undefined = QQmlExpression(QQmlEngine.contextForObject(item), item, "ToolTip.text").evaluate()
            assert not undefined
            tips.add((item.property("text"), text))
    card.deleteLater()
    assert tips >= {
        ("Fruity parametric EQ 2", "Égalisation / filtre · Lead"),
        ("Fruity Delay 3", "Delay · Lead · désactivé"),
        ("Fruity Reeverb 2", "Reverb · Lead · inaudible (mix à 0 %)"),
        ("Fruity Reeverb 2", "Reverb · Retour coupé · inaudible (insert coupé)"),
        ("Fruity Reeverb 2", "Reverb · Retour sans sortie · inaudible (insert sans sortie vers le Master)"),
        ("Fruity Reeverb 2", "Reverb · Effets coupés · désactivé"),
    }


# -- dry renders ----------------------------------------------------------------------------------

def test_a_return_with_its_fader_at_the_bottom_gets_no_dry_render(tmp_path):
    project = make_project(tmp_path / "Projet", [
        Insert(routes=()), Insert(name="Lead", routes=(0, 2)),
        Insert(name="Reverb", routes=(0,), volume=0, slots={0: Slot("Fruity Reeverb 2")}),
        Insert(name="Instru", routes=(0,))], [("Lead", 1)])
    assert not [j for j in plan_renders(_report(project)).jobs if j.kind == "vocal_dry"]
