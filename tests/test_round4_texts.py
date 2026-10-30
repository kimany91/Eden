"""Round 4 review fixes, texts: the render's warnings on the render page and in every mix, the
0 % wording, mixes saved before 0.4.0 shown again, true messages in "tu", the fader rule in the
fl-probe texts, and one list of export sample rates."""

import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from eden.cli import main
from eden.gui import viewmodel
from eden.mix.export import SAMPLE_RATES, ExportError, check_format, export_wav
from eden.mix.session import MixError, list_versions, mix_project
from eden.project.inspector import inspect_project
from eden.project.sources import SearchRoots
from eden.render.pipeline import RenderResult, render_project
from eden.render.plan import RenderPlan
from eden.render.probe import _space_slots
from eden.render.verify import NullTest
from eden.safety import Workspace
from eden.settings import Settings, save_settings
from flp_builder import Chan, Clip, Insert, Slot, build_flp
from test_render import SIM, make_session, sim_renderer
from test_round2_render import make_project

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "eden"
CUT_TAIL = "Leave remainder"


def _rendered(project):
    report = inspect_project(project, roots=SearchRoots())
    return report, render_project(project, sim_renderer(), timeout_s=120, report=report)


# -- 1. render warnings: shown on the render page, kept with each mix -------------------------

def test_the_render_warnings_are_kept_with_the_mix(tmp_path, monkeypatch):
    monkeypatch.setenv("EDEN_SIM_CUT_TAIL", "1")  # FL stops at the last clip: the echo tails are cut
    project = make_session(tmp_path)
    report, renders = _rendered(project)
    assert renders.ok and any(CUT_TAIL in w for w in renders.warnings)
    version = mix_project(project, report, renders, intensity=0.0)
    assert version.warnings[:len(renders.warnings)] == renders.warnings
    saved = list_versions(project)[0]
    assert saved["warnings"][:len(renders.warnings)] == renders.warnings
    assert any(CUT_TAIL in w for w in viewmodel.mix_view(saved)["warnings"])


def _controller():
    pytest.importorskip("PySide6.QtCore")
    from eden.gui.controller import EdenController

    return EdenController(check_updates=False)


def _result(warnings):
    passed = NullTest(True, -90.0, -90.0, -60.0, 0.0, "La somme des pistes reproduit le mix")
    return RenderResult("p.flp", "0" * 64, "renders", RenderPlan([]), [], passed, [], warnings)


def test_rendered_says_all_checked_only_without_warnings():
    c = _controller()
    c._on_rendered(_result([]))
    assert c.progressLabel == "Terminé : tout a été vérifié."
    c._on_rendered(_result(["Rendu silencieux : Lead seule"]))
    assert c.progressLabel == "Terminé, avec des points à vérifier (voir ci-dessous)."
    assert c.renderSummary["ok"] is True and c.renderSummary["warnings"] == ["Rendu silencieux : Lead seule"]


def test_the_render_page_shows_the_render_warnings(tmp_path, monkeypatch):
    QtGui = pytest.importorskip("PySide6.QtGui")
    from PySide6.QtCore import QObject
    from test_gui import wait_idle

    from eden.gui.app import create_engine, dispose
    from eden.gui.controller import EdenController

    monkeypatch.setenv("EDEN_SIM_CUT_TAIL", "1")
    _app = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])
    c = EdenController(renderer_factory=sim_renderer, check_updates=False)
    engine = create_engine(c, play_splash=False)
    try:
        c.openProject(str(make_session(tmp_path)))
        wait_idle(c)
        c.renderFromFl()
        wait_idle(c)
        warnings = c.renderSummary["warnings"]
        assert c.renderSummary["ok"] is True and any(CUT_TAIL in w for w in warnings)
        assert c.progressLabel == "Terminé, avec des points à vérifier (voir ci-dessous)."
        root = engine.rootObjects()[0]  # held: a found child dies with a temporary root's wrapper
        shown = root.findChild(QObject, "renderWarnings")
        assert shown.property("count") == len(warnings)

        c.intensity = 0.0
        c.mixProject()
        wait_idle(c)
        assert c.errorMessage == "", c.errorMessage
        assert any(CUT_TAIL in w for w in c.mixResult["warnings"])
        rates = root.findChild(QObject, "exportRate")
        assert rates.property("count") == 1 + len(SAMPLE_RATES)  # FL's own rate, then the export's list
        assert engine.load_warnings == []
    finally:
        dispose(engine)


def test_eden_mix_prints_each_render_warning_once(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("EDEN_SIM_CUT_TAIL", "1")
    save_settings(Settings(fl_path=sys.executable, render_args=[SIM, "/R", "/Ewav", "{project}"]))
    project = make_session(tmp_path)
    assert main(["mix", str(project), "--intensite", "0"]) == 0
    out = capsys.readouterr().out
    assert out.count(CUT_TAIL) == 1
    assert main(["render", str(project)]) == 0
    assert capsys.readouterr().out.count(CUT_TAIL) == 1


def test_eden_mix_prints_the_render_warnings_when_it_cannot_mix(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("EDEN_SIM_CUT_TAIL", "1")
    monkeypatch.setenv("EDEN_SIM_IGNORE_MUTE", "1")  # every group holds the whole song: the null test fails
    save_settings(Settings(fl_path=sys.executable, render_args=[SIM, "/R", "/Ewav", "{project}"]))
    assert main(["mix", str(make_session(tmp_path)), "--intensite", "0"]) == 2
    out, err = capsys.readouterr()
    assert out.count(CUT_TAIL) == 1  # no mix to carry it: said before the error
    assert "n'a pas passé ses vérifications" in err


# -- 2. what 0 % gives ----------------------------------------------------------------------

def test_zero_percent_is_described_as_the_mix_before_the_master():
    mix_page = (SRC / "gui" / "qml" / "MixPage.qml").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "0 % : ton mix tel que FL le joue avant le Master" in mix_page
    assert "morceau d'origine, à l'identique" not in mix_page
    assert "0 % = ton mix d'origine" in " ".join(readme.split())


# -- 3. a mix saved by 0.3.0 can be shown again ---------------------------------------------------

def _stats(lufs):
    return {"loudness_lufs": lufs, "true_peak_db": -1.0, "sample_peak_db": -1.2, "duration_s": 4.0,
            "sample_rate": 44100, "subtype": "FLOAT"}


def test_a_mix_saved_by_eden_0_3_0_is_shown_again(tmp_path):
    project = make_session(tmp_path)
    folder = Workspace(project).root / "mixes" / "20261029-150000"
    folder.mkdir(parents=True)
    sf.write(folder / "final.wav", np.zeros((441, 2)), 44100, subtype="FLOAT")
    old = {  # MixVersion as 0.3.0 wrote it: no song, master or checks; PartResult and Treatment shorter
        "id": "20261029-150000", "created_at": "2026-10-29T15:00:00+00:00", "intensity": 1.0,
        "final_wav": str(folder / "final.wav"),
        "parts": [{"key": "ch0", "label": "Lead", "role": "lead_vocal",
                   "treatments": [{"kind": "compressor", "label": "Compression", "reason": "écart de 6 dB",
                                   "params": {}}],
                   "loudness_before": -20.0, "loudness_after": -18.0}],
        "staging_gain_db": 0.0, "original": _stats(-11.0), "final": _stats(-9.0), "warnings": [],
    }
    (folder / "version.json").write_text(json.dumps(old), encoding="utf-8")
    saved = list_versions(project)
    assert viewmodel.versions_view(saved)[0]["lufs"] == "-9.0 LUFS"
    view = viewmodel.mix_view(saved[0])
    assert (view["checks"], view["platforms"], view["song"], view["master"]) == ([], [], [], [])
    assert view["parts"][0]["treatments"][0]["label"] == "Compression"
    assert view["final"]["lufs"] == "-9.0 LUFS" and view["untouched"] is False


# -- 4. no voice recognised: a true action, said once -------------------------------------------

def test_no_voice_recognised_tells_the_real_way_out(tmp_path):
    d = tmp_path / "Sans voix"
    d.mkdir()
    sf.write(d / "Piste 1.wav", 0.1 * np.ones((22050, 2)), 22050)
    flp = d / "Projet.flp"
    flp.write_bytes(build_flp([Chan("Piste 1", insert=1, sample_path=str(d / "Piste 1.wav"))],
                              [Insert(routes=()), Insert(name="Insert 1")], [Clip(1, 0, 96, channel=0)]))
    report = inspect_project(flp, roots=SearchRoots())
    assert not report.vocal_sources
    assert ("Aucune piste n'a été reconnue comme voix : renomme tes pistes de voix dans FL Studio "
            "(« Lead », « Double », « Backs », « Ad-lib »…) puis relance l'analyse.") in report.warnings
    assert not any("manuellement" in w for w in report.warnings)
    analysis_page = (SRC / "gui" / "qml" / "AnalysisPage.qml").read_text(encoding="utf-8")
    assert "Aucune voix reconnue" not in analysis_page  # the warning above is the only message


def test_the_suggested_names_give_a_voice_type():
    from eden.project.classify import guess_role

    assert [guess_role([("Canal", n)]).role for n in ("Lead", "Double", "Backs", "Ad-lib")] == \
        ["lead_vocal", "double", "back_vocal", "adlib"]


def test_a_voice_of_unknown_type_is_mixed_as_a_lead_and_the_docs_say_so():
    from eden.mix.space import design_space
    from eden.mix.vocal import LEAD_ROLES, PROFILES

    assert "vocal" in LEAD_ROLES and PROFILES["vocal"] == PROFILES["lead_vocal"]
    assert design_space(95.0, "vocal", 1.0) == design_space(95.0, "lead_vocal", 1.0)
    docs = " ".join((ROOT / "docs" / "mixage.md").read_text(encoding="utf-8").split())
    assert "(« Voix (type à confirmer) »" in docs and "est mixée comme une voix principale" in docs


# -- 5. "tu" everywhere, and the CLI's mix error names both ways to render ------------------------

def test_messages_say_tu():
    formal = re.compile(r"\b(?:vous|votre|vos)\b|\b(?!assez\b|chez\b)\w+ez\b", re.IGNORECASE)
    found = [f"{path.relative_to(SRC)}:{n}: {line.strip()}"
             for path in sorted(SRC.rglob("*")) if path.suffix in (".py", ".qml")
             for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
             if formal.search(line) and not line.strip().startswith("#")]
    assert found == []


def test_failed_renders_point_to_the_button_and_to_eden_render(tmp_path):
    project = make_session(tmp_path)
    report, renders = _rendered(project)
    renders.null_test.passed = False
    with pytest.raises(MixError) as err:
        mix_project(project, report, renders)
    assert "relance la récupération du son" in str(err.value)
    assert "« Récupérer le son depuis FL Studio »" in str(err.value) and "eden render" in str(err.value)


# -- 6. a return whose fader is at the bottom is never tried by fl-probe ---------------------------

@pytest.mark.parametrize("volume, tried", [(0, []), (1, [("Lead", "Fruity Reeverb 2")])])
def test_fl_probe_never_tries_a_return_whose_fader_is_at_the_bottom(tmp_path, volume, tried):
    project = make_project(tmp_path / "Projet", [
        Insert(routes=()), Insert(name="Lead", routes=(0, 2)),
        Insert(name="Reverb", routes=(0,), volume=volume, slots={0: Slot("Fruity Reeverb 2")}),
        Insert(name="Instru", routes=(0,))], [("Lead", 1)])
    report = inspect_project(project, roots=SearchRoots())
    sources = [s for s in report.sources if s.reaches_master]
    assert [(s.label, e.plugin) for s, e in _space_slots(report.project, sources)] == tried


def test_the_fader_rule_is_in_the_probe_and_plan_texts():
    import eden.render.probe as probe

    assert "return fader at the bottom" not in probe.__doc__
    assert "almost all the" in probe.__doc__
    for doc in ("01-audit-architecture.md", "02-plan-developpement.md"):
        text = " ".join((ROOT / "docs" / doc).read_text(encoding="utf-8").split())
        assert "fader du retour en bas" not in text
        assert "envoi ou retour presque tout en bas" in text
        assert "volume de l'insert au-dessus de zéro, insert qui atteint le Master), une copie" in text


# -- 7. stale texts ---------------------------------------------------------------------------------

def test_readme_and_audit_doc_match_the_code():
    from eden import __version__

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"## État actuel (v{__version__})" in readme
    assert "présence" not in readme
    audit = " ".join((ROOT / "docs" / "01-audit-architecture.md").read_text(encoding="utf-8").split())
    assert "pas d'Auto-Tune ajouté" not in audit and "correction manuelle dans l'interface" not in audit
    assert "Eden n'ajoute jamais de correction de hauteur" in audit


# -- 8. one list of export sample rates -------------------------------------------------------------

def test_export_refuses_a_rate_outside_the_list(tmp_path):
    src = tmp_path / "final.wav"
    sf.write(src, 0.1 * np.ones((4410, 2)), 44100, subtype="FLOAT")
    with pytest.raises(ExportError, match="22050 Hz .44100, 48000, 88200 ou 96000 Hz."):
        export_wav(src, tmp_path / "a", 22050, 24)
    with pytest.raises(ExportError, match="20 .16, 24 ou 32."):
        check_format(None, 20)
    check_format(None, 24)  # FL Studio's own rate
    assert export_wav(src, tmp_path / "b", 48000, 24).sample_rate == 48000
    assert not (tmp_path / "a.wav").exists()


def test_eden_mix_checks_the_rate_before_anything_else(tmp_path, capsys):
    assert main(["mix", str(make_session(tmp_path)), "--frequence", "22050"]) == 2
    err = capsys.readouterr().err
    assert "22050 Hz (44100, 48000, 88200 ou 96000 Hz)" in err and "fl-probe" not in err
    assert main(["mix", str(tmp_path / "Session" / "Session.flp"), "--bits", "20"]) == 2
    assert "16, 24 ou 32" in capsys.readouterr().err


def test_the_mix_page_offers_the_export_list():
    assert viewmodel.sample_rate_choices() == [
        {"label": "44,1 kHz", "value": 44100}, {"label": "48 kHz", "value": 48000},
        {"label": "88,2 kHz", "value": 88200}, {"label": "96 kHz", "value": 96000}]
    assert [c["value"] for c in viewmodel.sample_rate_choices()] == list(SAMPLE_RATES)
    cli = (SRC / "cli.py").read_text(encoding="utf-8")
    assert "44100" not in cli and "[16, 24, 32]" not in cli


def test_eden_does_not_load_the_export_module_to_start(tmp_path):
    import subprocess

    code = "import sys, eden.cli; print('eden.mix.export' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
                         env=dict(os.environ, PYTHONPATH=str(SRC.parent)))
    assert out.stdout.strip() == "False", out.stderr
