"""Round 2 review fixes: why an inactive FL effect is inactive (switched off or unheard), as the
report and the interface show it, and the fl-probe slot check that tries other slots before it
decides that FL does not bypass a slot."""

import os
import sys

import numpy as np
import pytest
import soundfile as sf

from eden.flp.edit import FlpEditor
from eden.gui import viewmodel
from eden.project.classify import RoleGuess
from eden.project.inspector import SourceAnalysis, _effects_on, _signal_path, inspect_project
from eden.project.model import FlpProject, MixerInsert, MixerSlot, PluginInfo, Route
from eden.project.sources import SearchRoots
from eden.render.fl_studio import FLStudioRenderer, RenderError
from eden.render.probe import SLOT_CHECK_TRIES, probe_fl_studio
from eden.report import _source_lines, render_markdown
from eden.settings import load_settings
from flp_builder import Chan, Clip, Insert, Slot, build_flp
from test_render import SIM

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
        MixerInsert(1, "Lead", routes=[Route(0), Route(2), Route(3), Route(4), Route(5)],
                    slots=[_slot(0, "Fruity parametric EQ 2"), _slot(1, "Fruity Delay 3", enabled=False),
                           _slot(2, "Fruity Reeverb 2", mix_raw=0)]),
        MixerInsert(2, "Retour coupé", enabled=False, routes=[Route(0)],
                    slots=[_slot(0, "Fruity Reeverb 2"), _slot(1, "Fruity Delay 3", enabled=False)]),
        MixerInsert(3, "Retour sans sortie", routes=[], slots=[_slot(0, "Fruity Reeverb 2")]),
        MixerInsert(4, "Vers un bus coupé", routes=[Route(6)], slots=[_slot(0, "Fruity Delay 3")]),
        MixerInsert(5, "Effets coupés", effects_enabled=False, routes=[Route(0)],
                    slots=[_slot(0, "Fruity Reeverb 2")]),
        MixerInsert(6, "Bus coupé", enabled=False, routes=[Route(0)]),
    ])


def _lead(project):
    path, reaches = _signal_path(project, 1)
    return SourceAnalysis(0, "Lead", "sampler", 1, "Lead", path, reaches,
                          _effects_on(project, [i for i in path if i]), RoleGuess("lead_vocal"), 1, 0.0, 2.0)


def test_an_inactive_effect_says_whether_it_is_switched_off_or_unheard():
    effects = {(e.insert_label, e.plugin): (e.active, e.inactive_reason)
               for e in _effects_on(_project(), [1, 2, 3, 4, 5])}
    assert effects == {
        ("Lead", "Fruity parametric EQ 2"): (True, None),
        ("Lead", "Fruity Delay 3"): (False, "off"),
        ("Lead", "Fruity Reeverb 2"): (False, "mix_zero"),
        ("Retour coupé", "Fruity Reeverb 2"): (False, "insert_muted"),
        ("Retour coupé", "Fruity Delay 3"): (False, "off"),  # its own switch comes first
        ("Retour sans sortie", "Fruity Reeverb 2"): (False, "no_output"),
        ("Vers un bus coupé", "Fruity Delay 3"): (False, "no_output"),
        ("Effets coupés", "Fruity Reeverb 2"): (False, "off"),
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
                  "Effets coupés / slot 1 : Fruity Reeverb 2 [Reverb] — désactivé"):
        assert shown in lines


@pytest.mark.parametrize("reverb_insert,shown", [
    ({"enabled": False}, "inaudible (insert coupé)"),
    ({"routes": ()}, "inaudible (insert sans sortie vers le Master)"),
    ({"slots": {0: Slot("Fruity Reeverb 2", enabled=False)}}, "désactivé"),
], ids=["muted", "routed-nowhere", "switched-off"])
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


# -- R2: fl-probe tries other slots before failing -----------------------------------------------

def _probe(project, tmp_path):
    settings = tmp_path / "settings.json"
    res = probe_fl_studio(project, command=[sys.executable, SIM], timeout_s=120,
                          settings_file=settings, log=lambda m: None)
    return res, load_settings(settings)


def _slot_lines(res):
    return [line for line in res.lines if line.startswith("Test d'isolation (slot d'effet contourné")]


@pytest.fixture
def renders(monkeypatch):
    """Names of the probe's copies FL renders, in order."""
    seen = []
    render = FLStudioRenderer.render

    def counting(self, project_copy, timeout_s):
        seen.append(project_copy.parent.name)
        return render(self, project_copy, timeout_s)

    monkeypatch.setattr(FLStudioRenderer, "render", counting)
    return seen


def test_a_slot_that_changes_nothing_is_followed_by_another(tmp_path):
    # The reverb return's fader is at the bottom: bypassing its reverb changes nothing, though FL
    # bypasses it. The back's delay then shows that FL does bypass a slot.
    project = make_project(tmp_path / "Projet", [
        Insert(routes=()), Insert(name="Lead", routes=(0, 2)),
        Insert(name="Reverb", routes=(0,), volume=0, slots={0: Slot("Fruity Reeverb 2")}),
        Insert(name="Back", routes=(0,), slots={0: Slot("Fruity Delay 3")}),
        Insert(name="Instru", routes=(0,))], [("Lead", 1), ("Back", 3)])
    res, settings = _probe(project, tmp_path)
    lines = _slot_lines(res)
    assert len(lines) == 2
    assert lines[0] == ("Test d'isolation (slot d'effet contourné, essai 1 sur 2 : « Fruity Reeverb 2 » sur "
                        "« Reverb », Lead seule) : le rendu ne change pas (écart sous -60 dB) ✘")
    assert lines[1].startswith("Test d'isolation (slot d'effet contourné, essai 2 sur 2 : « Fruity Delay 3 » "
                               "sur « Back », Back seule) : le rendu change (écart de ")
    assert lines[1].endswith(" dB) ✔")
    assert res.isolation_slots_ok is True and res.ok
    assert settings.render_args


def test_the_check_fails_only_when_no_slot_tried_changes_the_render(tmp_path, monkeypatch, renders):
    monkeypatch.setenv("EDEN_SIM_IGNORE_SLOTS", "1")  # FL plays bypassed slots
    project = make_project(tmp_path / "Projet", [
        Insert(routes=()),
        Insert(name="Lead", routes=(0,), slots={0: Slot("Fruity Reeverb 2"), 1: Slot("Fruity Delay 3")}),
        Insert(name="Back", routes=(0,), slots={0: Slot("Fruity Reeverb 2")}),
        Insert(name="Adlib", routes=(1,)),
        Insert(name="Instru", routes=(0,))], [("Lead", 1), ("Back", 2), ("Adlib", 3)])
    res, settings = _probe(project, tmp_path)
    lines = _slot_lines(res)
    # 5 candidates; a new insert, then a new slot, with a new source if there is one; 3 tries at most
    assert SLOT_CHECK_TRIES == 3 and len(lines) == 4
    assert [line.split(" : ")[1].split(")")[0] for line in lines[:3]] == [
        "« Fruity Reeverb 2 » sur « Lead », Lead seule",
        "« Fruity Reeverb 2 » sur « Back », Back seule",
        "« Fruity Delay 3 » sur « Lead », Adlib seule"]
    assert all(line.endswith("le rendu ne change pas (écart sous -60 dB) ✘") for line in lines[:3])
    assert lines[3] == ("Test d'isolation (slot d'effet contourné) : aucun des 3 essais ne montre que "
                        "FL Studio contourne un slot désactivé ✘")
    assert res.isolation_slots_ok is False and not res.ok
    assert settings.render_args is None  # nothing saved
    assert [r for r in renders if r.startswith("isolation-slot")] == [
        "isolation-slot-1-actif", "isolation-slot-1-contourne", "isolation-slot-2-actif",
        "isolation-slot-2-contourne", "isolation-slot-3-actif", "isolation-slot-3-contourne"]


def test_a_slot_already_tried_waits_until_no_other_slot_is_left(tmp_path, monkeypatch):
    # Every voice plays through a vocal bus holding a reverb then a delay. The reverb lets the
    # sound through (bypassing it changes nothing, emulated here); the delay is bypassed as asked.
    # Trying the reverb again with the other voices would end in a false failure.
    bypass = FlpEditor.set_slot_enabled

    def reverb_passes_through(self, insert, slot, enabled):
        if (insert, slot) != (4, 0):
            bypass(self, insert, slot, enabled)

    monkeypatch.setattr(FlpEditor, "set_slot_enabled", reverb_passes_through)
    project = make_project(tmp_path / "Projet", [
        Insert(routes=()), Insert(name="Lead", routes=(4,)), Insert(name="Adlib", routes=(4,)),
        Insert(name="Back", routes=(4,)),
        Insert(name="Bus voix", routes=(0,), slots={0: Slot("Fruity Reeverb 2"), 1: Slot("Fruity Delay 3")}),
        Insert(name="Instru", routes=(0,))], [("Lead", 1), ("Adlib", 2), ("Back", 3)])
    res, settings = _probe(project, tmp_path)
    lines = _slot_lines(res)
    assert len(lines) == 2
    assert lines[0] == ("Test d'isolation (slot d'effet contourné, essai 1 sur 3 : « Fruity Reeverb 2 » sur "
                        "« Bus voix », Lead seule) : le rendu ne change pas (écart sous -60 dB) ✘")
    assert lines[1].startswith("Test d'isolation (slot d'effet contourné, essai 2 sur 3 : « Fruity Delay 3 » "
                               "sur « Bus voix », Adlib seule) : le rendu change (écart de ")
    assert res.isolation_slots_ok is True and res.ok and settings.render_args


def test_a_source_is_rendered_alone_once_for_all_its_slots(tmp_path, monkeypatch, renders):
    monkeypatch.setenv("EDEN_SIM_IGNORE_SLOTS", "1")
    project = make_project(tmp_path / "Projet", [
        Insert(routes=()),
        Insert(name="Lead", routes=(0, 2), slots={0: Slot("Fruity Reeverb 2"), 1: Slot("Fruity Delay 3")}),
        Insert(name="Delay", routes=(0,), slots={0: Slot("Fruity Delay 3")}),
        Insert(name="Instru", routes=(0,))], [("Lead", 1)])
    res, _ = _probe(project, tmp_path)
    assert [line.split(" : ")[1].split(")")[0] for line in _slot_lines(res)[:3]] == [
        "« Fruity Reeverb 2 » sur « Lead », Lead seule",
        "« Fruity Delay 3 » sur « Delay », Lead seule",  # another insert first
        "« Fruity Delay 3 » sur « Lead », Lead seule"]
    assert [r for r in renders if r.startswith("isolation-slot")] == [
        "isolation-slot-1-actif", "isolation-slot-1-contourne", "isolation-slot-2-contourne",
        "isolation-slot-3-contourne"]
    assert res.isolation_slots_ok is False


def test_a_silent_solo_render_moves_on_to_the_next_slot(tmp_path):
    project = make_project(tmp_path / "Projet", [
        Insert(routes=()), Insert(name="Lead", routes=(0,), slots={0: Slot("Fruity Reeverb 2")}),
        Insert(name="Back", routes=(0,), slots={0: Slot("Fruity Delay 3")}),
        Insert(name="Instru", routes=(0,))], [("Lead", 1), ("Back", 2)], silent={"Lead"})
    res, settings = _probe(project, tmp_path)
    lines = _slot_lines(res)
    assert lines[0] == ("Test d'isolation (slot d'effet contourné, essai 1 sur 2 : « Fruity Reeverb 2 » sur "
                        "« Lead », Lead seule) : non vérifié (rendu silencieux)")
    assert "le rendu change" in lines[1] and len(lines) == 2
    assert res.isolation_slots_ok is True and res.ok and settings.render_args


def test_only_silent_solo_renders_leave_the_check_unverified(tmp_path):
    project = make_project(tmp_path / "Projet", [
        Insert(routes=()), Insert(name="Lead", routes=(0,), slots={0: Slot("Fruity Reeverb 2")}),
        Insert(name="Instru", routes=(0,))], [("Lead", 1)], silent={"Lead"})
    res, settings = _probe(project, tmp_path)
    assert _slot_lines(res) == ["Test d'isolation (slot d'effet contourné, essai 1 sur 1 : « Fruity Reeverb 2 » "
                                "sur « Lead », Lead seule) : non vérifié (rendu silencieux)"]
    assert res.isolation_slots_ok is None and res.ok and settings.render_args


def test_a_failed_render_is_followed_by_another_slot(tmp_path, monkeypatch):
    render = FLStudioRenderer.render

    def failing_once(self, project_copy, timeout_s):
        if project_copy.parent.name == "isolation-slot-1-contourne":
            raise RenderError("FL Studio s'est arrêté (code 1) sans produire de fichier WAV")
        return render(self, project_copy, timeout_s)

    monkeypatch.setattr(FLStudioRenderer, "render", failing_once)
    project = make_project(tmp_path / "Projet", [
        Insert(routes=()), Insert(name="Lead", routes=(0,), slots={0: Slot("Fruity Reeverb 2")}),
        Insert(name="Back", routes=(0,), slots={0: Slot("Fruity Delay 3")}),
        Insert(name="Instru", routes=(0,))], [("Lead", 1), ("Back", 2)])
    res, settings = _probe(project, tmp_path)
    lines = _slot_lines(res)
    assert lines[0] == ("Test d'isolation (slot d'effet contourné, essai 1 sur 2 : « Fruity Reeverb 2 » sur "
                        "« Lead », Lead seule) : échec du rendu (FL Studio s'est arrêté (code 1) sans produire "
                        "de fichier WAV) ✘")
    assert "le rendu change" in lines[1] and len(lines) == 2
    assert res.isolation_slots_ok is True and res.ok and settings.render_args
