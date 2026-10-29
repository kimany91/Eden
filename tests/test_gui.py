"""The QML interface, driven through its controller (offscreen, software rendering)."""

import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
QtGui = pytest.importorskip("PySide6.QtGui")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402

from eden.gui.app import create_engine, dispose  # noqa: E402
from eden.gui.controller import EdenController  # noqa: E402
from test_render import SIM, make_session, sim_renderer  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def wait_idle(c, timeout_ms=120000):
    waited = 0
    while c.busy and waited < timeout_ms:
        pump(50)
        waited += 50
    assert not c.busy, "operation did not finish"


@pytest.fixture
def ui(app):
    created = []

    def make(**kw):
        c = EdenController(check_updates=False, **kw)
        engine = create_engine(c, play_splash=False)
        created.append((engine, c))
        return c, engine

    yield make
    for engine, _ in created:
        dispose(engine)


def test_interface_loads_without_warnings(ui):
    c, engine = ui()
    pump(200)
    assert engine.load_warnings == []
    root = engine.rootObjects()[0]
    assert root.property("title") == "Eden"
    assert len(c.treeTriangles) > 100  # logo geometry for the opening animation


def test_splash_plays_then_reveals_the_app(app):
    c = EdenController(check_updates=False)
    engine = create_engine(c, play_splash=True)
    root = engine.rootObjects()[0]
    assert root.property("splashDone") is False
    for _ in range(80):
        pump(100)
        if root.property("splashDone"):
            break
    assert root.property("splashDone") is True
    dispose(engine)


def test_analysis_then_render(ui, tmp_path):
    project = make_session(tmp_path)
    configured = {"ok": False}

    def factory():
        return sim_renderer() if configured["ok"] else None

    def probe(path, log):
        from eden.render.probe import probe_fl_studio

        res = probe_fl_studio(path, command=[sys.executable, SIM], timeout_s=120, log=log)
        configured["ok"] = res.ok
        return res

    c, engine = ui(renderer_factory=factory, probe=probe)
    c.openProject(str(project))
    assert c.stage == "analyzing"
    wait_idle(c)
    assert c.stage == "analyzed" and c.errorMessage == ""
    assert [v["roleKey"] for v in c.report["voices"]] == ["lead_vocal", "adlib"]
    assert [s["status"] for s in c.analysisSteps] == ["done"] * 6

    c.renderFromFl()
    assert c.stage == "rendering"
    wait_idle(c)
    assert c.errorMessage == "", c.errorMessage
    assert c.stage == "rendered" and c.renderSummary["ok"] is True
    assert c.probeLog, "first use must run the FL Studio set-up test"
    statuses = {r["name"]: r["status"] for r in c.renderRows}
    assert set(statuses.values()) == {"done"}
    assert "controle-eden-0" in statuses
    assert engine.load_warnings == []


def test_errors_name_the_step(ui, tmp_path):
    bad = tmp_path / "abime.flp"
    bad.write_bytes(b"pas un projet")
    c, _ = ui()
    c.openProject(str(bad))
    wait_idle(c)
    assert c.stage == "home"
    assert c.errorStep == "Décodage du projet"
    c.clearError()
    assert c.errorMessage == ""


def test_missing_fl_studio_asks_for_its_location(ui, tmp_path, monkeypatch):
    monkeypatch.delenv("EDEN_FL_PATH", raising=False)
    c, _ = ui()  # real settings: nothing configured, no FL Studio on this machine
    c.openProject(str(make_session(tmp_path)))
    wait_idle(c)
    c.renderFromFl()
    wait_idle(c)
    assert c.errorStep == "Recherche de FL Studio"
    assert c.needsFlPath is True
    assert c.stage == "analyzed"

    fake_fl = tmp_path / "FL64.exe"
    fake_fl.write_bytes(b"")
    c.setFlStudioPath(str(fake_fl))
    from eden.settings import load_settings

    assert load_settings().fl_path == str(fake_fl) and c.needsFlPath is False


def test_launcher_self_test(tmp_path):
    import subprocess

    log = tmp_path / "selftest.log"
    env = dict(os.environ, EDEN_HOME=str(tmp_path / "home"))
    proc = subprocess.run([sys.executable, "-m", "eden.launcher", "--self-test", str(log)],
                          env=env, timeout=120)
    text = log.read_text(encoding="utf-8")
    assert proc.returncode == 0, text
    assert "OK" in text and "libsndfile" in text


def test_mix_page_flow(ui, tmp_path):
    from pathlib import Path

    c, engine = ui(renderer_factory=sim_renderer)
    c.openProject(str(make_session(tmp_path)))
    wait_idle(c)
    c.renderFromFl()
    wait_idle(c)
    assert c.renderSummary["ok"] is True

    c.intensity = 0.6
    assert c.intensity == pytest.approx(0.6)
    c.mixProject()
    assert c.stage == "mixing"
    wait_idle(c)
    assert c.stage == "mixed" and c.errorMessage == "", c.errorMessage
    assert [s["status"] for s in c.mixSteps] == ["done"] * 4
    first = c.mixResult["id"]
    assert c.mixResult["intensity"] == 60
    assert c.mixResult["parts"][-1]["roleKey"] == "rest"
    assert len(c.mixVersions) == 1

    c.intensity = 0.0
    c.mixProject()
    wait_idle(c)
    assert c.mixResult["untouched"] is True
    assert [v["id"] for v in c.mixVersions][1] == first
    c.showVersion(first)
    assert c.mixResult["id"] == first

    out = tmp_path / "exports"
    out.mkdir()
    c.setExportFolder(str(out))
    c.exportWav("Mon son - Eden", 48000, 24)
    wait_idle(c)
    assert (out / "Mon son - Eden.wav").is_file()
    assert "48 kHz, 24 bits" in c.exportMessage and c.stage == "mixed"
    c.exportWav("Mon son - Eden", 48000, 24)  # same name again: refused, nothing overwritten
    wait_idle(c)
    assert c.errorStep == "Export du WAV" and "existe déjà" in c.errorMessage
    assert sorted(p.name for p in out.iterdir()) == ["Mon son - Eden.wav"]
    assert engine.load_warnings == []
    assert not list(Path(os.environ["EDEN_HOME"]).rglob("*.flp"))
