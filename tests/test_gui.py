import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from eden.gui.app import MainWindow  # noqa: E402
from test_inspector import rap_project  # noqa: E402,F401  (fixture)


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_analysis_fills_the_window(app, rap_project):  # noqa: F811
    w = MainWindow(check_updates=False)
    assert not w.btn_analyze.isEnabled()
    w.set_project(rap_project)
    assert w.btn_analyze.isEnabled()
    w.start_analysis()
    w.worker.wait(10000)
    app.processEvents()
    assert w.error.text() == ""
    assert w.progress.format() == "Analyse terminée"
    voix = w.sources_tree.topLevelItem(0)
    assert voix.text(0) == "Voix (3)"
    roles = {voix.child(i).text(1) for i in range(voix.childCount())}
    assert roles == {"Voix principale", "Ad-lib", "Voix (type à confirmer)"}
    assert w.btn_save.isEnabled()


def test_failure_names_the_step(app, tmp_path):
    bad = tmp_path / "corrompu.flp"
    bad.write_bytes(b"not an flp file at all")
    w = MainWindow(check_updates=False)
    w.set_project(bad)
    w.start_analysis()
    w.worker.wait(10000)
    app.processEvents()
    assert "Décodage du projet" in w.error.text()
    assert w.progress.format() == "Échec"
    assert not w.btn_save.isEnabled()


def _analyse(app, w, path):
    w.set_project(path)
    w.start_analysis()
    w.worker.wait(10000)
    app.processEvents()


def test_render_button_runs_probe_then_renders(app, tmp_path):
    import sys

    from test_render import SIM, make_session, sim_renderer

    from eden.render.probe import probe_fl_studio

    project = make_session(tmp_path)

    configured = {"ok": False}

    def factory():
        return sim_renderer() if configured["ok"] else None

    def probe(path, log):
        res = probe_fl_studio(path, command=[sys.executable, SIM], timeout_s=120, log=log)
        configured["ok"] = res.ok
        return res

    w = MainWindow(check_updates=False, renderer_factory=factory, probe=probe)
    assert not w.btn_render.isEnabled()
    _analyse(app, w, project)
    assert w.btn_render.isEnabled()
    w.start_render()
    w.render_worker.wait(120000)
    app.processEvents()
    assert w.error.text() == "", w.error.text()
    assert w.progress.format() == "Son récupéré"
    assert w.render_result.ok
    assert w.render_tree.topLevelItemCount() == len(w.render_result.jobs)
