"""The QML interface, driven through its controller (offscreen, software rendering)."""

import os
import sys

import numpy as np
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


def wait_journey(c, timeout_ms=180000):
    """The whole journey, then its end played by the interface (the apple), up to the result."""
    waited = 0
    while (c.busy or c.journeyActive) and waited < timeout_ms:
        pump(50)
        waited += 50
    assert not c.busy and not c.journeyActive, "the journey did not finish"


def test_one_journey_from_the_project_to_the_result(ui, tmp_path):
    from PySide6.QtCore import QObject

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
    growth, stages, shown = [], [], {}
    c.growthChanged.connect(lambda: growth.append(c.growth))
    c.journeyStageChanged.connect(lambda: stages.append(c.journeyStage))
    root = engine.rootObjects()[0]

    def at_the_end():  # the garden is still shown: its journal holds every line
        if c.journeyFinished:
            shown["lines"] = root.findChild(QObject, "journal").property("count")

    c.journeyFinishedChanged.connect(at_the_end)
    c.openProject(str(project))
    assert c.stage == "analyzing" and c.journeyActive
    wait_journey(c)

    # analysis, FL Studio's renders, the mix, the master, the checks: in one go, the tree never shrinks
    assert c.errorMessage == "" and c.stage == "mixed"
    assert stages == ["analysis", "render", "mix", "master", "checks"]
    assert growth == sorted(growth) and growth[-1] == 1.0 and len(growth) > 20
    assert [v["roleKey"] for v in c.report["voices"]] == ["lead_vocal", "adlib"]
    assert c.probeLog, "first use must run the FL Studio set-up test"
    assert c.renderSummary["ok"] is True and {r["status"] for r in c.renderRows} == {"done"}
    assert c.mixResult["id"] and c.mixResult["originalWav"].endswith("original.wav")

    lines = c.journeyLines()
    assert shown["lines"] == len(lines)
    text = "\n".join(f"{line['kind']} {line['text']}" for line in lines)
    for said in ("stage Analyse du projet", "detail Voix trouvée : « Lead » → Voix principale",
                 "stage FL Studio joue tes pistes", "step Rendu FL Studio : ", "step Rendu par FL Studio : Lead seule",
                 "done Somme des pistes = mix d'origine", "stage Mixage Eden",
                 "step Voix « Lead » : mesures", "detail « Lead » : Coupe-bas", "stage Mastering Eden",
                 # the project's "Instru" is a complete beat: kept as it is, not squashed a second time
                 "instru complète, déjà mixée et masterisée", "step Écrêtage doux puis limiteur, passage 1",
                 "done Avec Eden : -"):
        assert said in text, said
    assert all(line["time"][2] == ":" for line in lines)
    assert engine.load_warnings == []


def test_errors_name_the_step(ui, tmp_path):
    bad = tmp_path / "abime.flp"
    bad.write_bytes(b"pas un projet")
    c, _ = ui()
    c.openProject(str(bad))
    wait_idle(c)
    assert c.stage == "home" and not c.journeyActive  # the garden closes on the error
    assert c.errorStep == "Décodage du projet"
    assert c.journeyLines()[-1]["kind"] == "error"
    c.clearError()
    assert c.errorMessage == ""


def test_the_tree_grows_and_the_camera_follows_without_a_jump(ui):
    # each step of the work is seen growing (eased, never past the work done, the percentage with it), and the
    # camera reframes the taller tree gliding over many frames
    from PySide6.QtCore import QObject

    c, engine = ui()
    c._begin_journey("analysis", fresh=True)
    pump(400)
    root = engine.rootObjects()[0]  # held: a found child dies with a temporary root's wrapper
    view = root.findChild(QObject, "garden")
    start = view.property("camDistance")
    c._set("growth", 0.6)
    shown, cams = [], []
    for _ in range(80):
        pump(40)
        shown.append(view.property("shown"))
        cams.append(view.property("camDistance"))
    assert shown == sorted(shown) and max(shown) <= 0.6 + 1e-9 and shown[-1] == pytest.approx(0.6, abs=1e-3)
    moves = np.diff([start, *cams])
    assert cams[-1] - start > 3 and np.all(moves >= -1e-9) and moves.max() < 0.35 * (cams[-1] - start)
    c._set("growth", 0.1)  # a new journey: wound back as smoothly
    pump(40)
    assert view.property("shown") > 0.1


def test_the_garden_closes_cleanly_however_fast_an_error_comes(ui, tmp_path):
    # opened and closed at once, again and again: its journal must not be touched once it is closing
    # (a scroll scheduled for later did, and crashed Eden in one try out of a few)
    bad = tmp_path / "abime.flp"
    bad.write_bytes(b"pas un projet")
    c, engine = ui()
    for _ in range(60):
        c.openProject(str(bad))
        wait_idle(c)
        assert not c.journeyActive
        pump(20)
    assert engine.load_warnings == []


def test_a_click_on_a_project_of_the_folder_opens_it(ui, tmp_path):
    from PySide6.QtCore import QObject, QPointF, Qt
    from PySide6.QtTest import QTest

    projects = tmp_path / "Projects"
    (projects / "Mon son").mkdir(parents=True)
    (projects / "Mon son" / "Mon son.flp").write_bytes(b"pas un projet")  # the newest, first in the list
    (projects / "Backup").mkdir()
    (projects / "Backup" / "Mon son (overwritten at 1534h27).flp").write_bytes(b"pas un projet")
    c, engine = ui()
    c.setProjectsFolder(str(projects))
    root = engine.rootObjects()[0]
    pump(1200)  # the page has risen into place
    projects_list = root.findChild(QObject, "projectList")
    assert projects_list.property("count") == 1  # FL's backup is not a song to mix
    row = projects_list.mapToScene(QPointF(projects_list.width() / 2, 30)).toPoint()
    QTest.mouseClick(root, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, row)
    wait_idle(c)
    assert c.projectName == "Mon son" and c.errorStep == "Décodage du projet"  # opened, then read
    assert engine.load_warnings == []


def test_the_fl_studio_set_up_report_can_be_seen_and_copied(ui):
    from PySide6.QtCore import QObject

    c, engine = ui()
    c._set("projectName", "Vertige")
    c._set("report", {"flVersion": "25.1.6.4997"})
    c._set("probeLog", ["FL Studio : C:/FL64.exe", "Test d'isolation (canaux coupés) : le son reste présent ✘"])
    c._set("errorStep", "Configuration de FL Studio")
    c._set("errorMessage", "Rendu possible, mais l'isolation des pistes n'est pas fiable")
    pump(300)
    root = engine.rootObjects()[0]
    shown = {o.property("text") for o in root.findChildren(QObject) if o.property("visible") is True}
    assert {"Voir le compte rendu", "Copier le compte rendu"} <= shown
    c.copyProbeLog()
    assert QtGui.QGuiApplication.clipboard().text() == (
        "Eden " + c.version + " · FL Studio 25.1.6.4997 · projet « Vertige »\n"
        "FL Studio : C:/FL64.exe\nTest d'isolation (canaux coupés) : le son reste présent ✘")


def test_missing_fl_studio_asks_for_its_location(ui, tmp_path, monkeypatch):
    monkeypatch.delenv("EDEN_FL_PATH", raising=False)
    c, _ = ui()  # real settings: nothing configured, no FL Studio on this machine
    c.openProject(str(make_session(tmp_path)))
    wait_idle(c)  # the analysis goes on to the renders by itself
    assert c.errorStep == "Recherche de FL Studio"
    assert c.needsFlPath is True
    assert c.stage == "analyzed" and not c.journeyActive
    assert c.growth == pytest.approx(0.08)  # the tree waits at the end of the analysis

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
    c.intensity = 0.6
    assert c.intensity == pytest.approx(0.6)
    c.openProject(str(make_session(tmp_path)))
    wait_journey(c)
    assert c.stage == "mixed" and c.errorMessage == "", c.errorMessage
    first = c.mixResult["id"]
    assert c.mixResult["intensity"] == 60
    # voices, then the groups; the toy beat's tones cover the voices by more than 12 dB, where a dip uncovers
    # nothing: nothing is carved, so the rest of the mix has no line
    assert [p["roleKey"] for p in c.mixResult["parts"][2:]] == ["bass", "beat"]
    assert len(c.mixVersions) == 1

    # a remix is a new growth, from where the mix starts: the journal starts again
    cleared, growth = [], []
    c.logCleared.connect(lambda: cleared.append(True))
    c.growthChanged.connect(lambda: growth.append(c.growth))
    c.intensity = 0.0
    c.mixProject()
    assert c.stage == "mixing" and c.journeyActive and cleared
    wait_journey(c)
    assert growth[0] == pytest.approx(0.40) and growth == sorted(growth) and growth[-1] == 1.0
    assert c.journeyLines()[0]["text"] == "Mixage Eden"
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
