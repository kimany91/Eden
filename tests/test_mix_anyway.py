"""When the parts FL rendered do not sum back to the song, the user is not stuck: they can mix anyway
(mix/session.py, gui/controller.py). What Eden could not separate stays as it is, and the mix says so."""

from pathlib import Path

import pytest

from eden.mix.session import MixError, mix_project
from eden.project.inspector import inspect_project
from eden.project.sources import SearchRoots
from eden.render import pipeline as pipeline_mod
from eden.render.pipeline import render_project
from test_render import make_session, sim_renderer


@pytest.fixture
def unsplit(monkeypatch):
    """A render plan that forgets the 808's group: its parts no longer sum to the song."""
    real_plan = pipeline_mod.plan_renders

    def plan_missing_a_group(report):
        plan = real_plan(report)
        plan.jobs = [j for j in plan.jobs if j.name != "stem-005-808"]
        return plan

    monkeypatch.setattr(pipeline_mod, "plan_renders", plan_missing_a_group)


def test_parts_that_do_not_sum_to_the_song_are_mixed_only_when_asked(tmp_path, unsplit):
    project = make_session(tmp_path)
    report = inspect_project(project, roots=SearchRoots())
    renders = render_project(project, sim_renderer(), timeout_s=120, report=report)
    assert renders.complete and not renders.ok
    with pytest.raises(MixError, match="vérifications"):
        mix_project(project, report, renders, 1.0)
    version = mix_project(project, report, renders, 1.0, unchecked=True)
    assert Path(version.final_wav).is_file()
    assert version.warnings[0].startswith("Mixé à ta demande alors que la somme des pistes ne redonnait pas")


def test_the_render_page_offers_to_mix_anyway(tmp_path, unsplit):
    QtGui = pytest.importorskip("PySide6.QtGui")
    from test_gui import wait_idle, wait_journey

    from eden.gui.controller import EdenController

    _app = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])
    c = EdenController(renderer_factory=sim_renderer, check_updates=False)
    c.openProject(str(make_session(tmp_path)))
    wait_journey(c)  # it stops once the check fails
    summary = c.renderSummary
    assert summary["ok"] is False and summary["complete"] is True and "mixe quand même" in summary["verdict"]
    assert c.stage == "rendered" and not c.mixResult
    c.mixProject()  # the usual button does not mix renders that failed their check
    assert not c.busy and not c.mixResult
    c.mixAnyway()
    wait_idle(c)
    assert c.errorMessage == "", c.errorMessage
    assert c.mixResult and c.mixResult["warnings"][0].startswith("Mixé à ta demande")
    c.mixProject()  # mixed again (another intensity...) the way the user chose for these renders
    wait_idle(c)
    assert c.errorMessage == ""
