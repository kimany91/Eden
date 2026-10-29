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
