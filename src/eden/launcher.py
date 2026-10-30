"""Entry point of the installed Windows application (no console).

``Eden.exe``                      opens the interface
``Eden.exe --self-test <log>``    loads the whole interface off-screen and
                                  exits 0 if it works (used to check every
                                  installer before it is published)
``Eden.exe --render-test <png>``  draws the grown garden in a window with the
                                  PC's own graphics (Direct3D on Windows), saves
                                  the image (and its report, <png>.txt) and exits
                                  0 if the tree is there
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path


def _setup_logging() -> Path:
    from eden.safety import eden_home

    log_dir = eden_home() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "eden.log"
    logging.basicConfig(filename=log_file, level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    def excepthook(kind, value, tb):
        logging.critical("Erreur non gérée :\n%s", "".join(traceback.format_exception(kind, value, tb)))
        sys.__excepthook__(kind, value, tb)

    sys.excepthook = excepthook
    return log_file


def self_test(report: Path) -> int:
    """Load the real interface off-screen and check it; write the outcome to ``report``."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QT_QUICK_BACKEND"] = "software"
    lines: list[str] = []
    code = 1
    try:
        from PySide6.QtCore import QEventLoop, QTimer
        from PySide6.QtGui import QGuiApplication

        from eden import __version__
        from eden.gui.app import create_engine, dispose
        from eden.gui.controller import EdenController

        app = QGuiApplication(sys.argv[:1])
        controller = EdenController(check_updates=False)
        engine = create_engine(controller, play_splash=True)
        loop = QEventLoop()
        QTimer.singleShot(1500, loop.quit)
        loop.exec()
        warnings = list(engine.load_warnings)
        lines.append(f"Eden {__version__}")
        lines.append(_audio_check())
        lines.append(f"triangles du logo : {len(controller.treeTriangles)}")
        garden_errors = _garden_check(engine)
        lines.append("jardin 3D et écoute : " + ("chargés" if not garden_errors else "ÉCHEC"))
        lines.extend(garden_errors)
        lines.extend(f"avertissement QML : {w}" for w in warnings)
        ok = (not warnings and not garden_errors and len(controller.treeTriangles) > 100
              and bool(engine.rootObjects()))
        dispose(engine)
        del app
        code = 0 if ok else 1
        lines.append("OK" if ok else "ÉCHEC")
    except Exception:
        lines.append(traceback.format_exc())
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return code


RENDER_QML = """
import QtQuick
import "%s"
Window {
    width: 960; height: 600; visible: true
    Rectangle {  // the garden's blue sky, as in Eden
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#2F6DC6" }
            GradientStop { position: 0.32; color: "#5E9BE0" }
            GradientStop { position: 0.6; color: "#CFE6F7" }
        }
    }
    GardenScene {
        objectName: "scene"; anchors.fill: parent
        growth: 1; time: 2; yaw: 35; pitch: -9; distance: %f
        target: Qt.vector3d(0, %f, 0)
    }
}
"""


def render_test(image: Path) -> int:
    """The self-test renders nothing: here the garden is drawn for real, so that the shaders Qt
    compiles on the fly for this PC's graphics API run. The tree must cover part of the image in
    its yellows, and Qt must report no shader or pipeline error."""
    import numpy as np
    from PySide6.QtCore import QEventLoop, QTimer, QtMsgType, QUrl, qInstallMessageHandler
    from PySide6.QtGui import QGuiApplication, QImage
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickWindow  # noqa: F401  (the root object is a QQuickWindow)

    from eden.gui import garden_qml  # noqa: F401  (Eden.Garden)
    from eden.gui.app import QML_DIR
    from eden.gui.garden import grow_tree

    problems: list[str] = []

    def messages(kind, _context, text) -> None:
        if kind in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg) and any(
                word in text.lower() for word in ("shader", "pipeline", "material", "qrhi", "failed")):
            problems.append(text)

    report: list[str] = []

    def done(code: int) -> int:  # the installed app has no console: the report goes next to the image
        image.with_suffix(".txt").write_text("\n".join([*report, "OK" if code == 0 else "ÉCHEC"]) + "\n",
                                             encoding="utf-8")
        return code

    qInstallMessageHandler(messages)
    app = QGuiApplication(sys.argv[:1])
    height = float(grow_tree().heights[-1])
    engine = QQmlApplicationEngine()
    engine.warnings.connect(lambda ws: problems.extend(w.toString() for w in ws))
    engine.loadData((RENDER_QML % (QUrl.fromLocalFile(str(QML_DIR)).toString(), 1.0 + height * 2.1,
                                   0.05 + height * 0.5)).encode())
    if not engine.rootObjects():
        report.extend(problems or ["fenêtre non créée"])
        return done(1)
    window = engine.rootObjects()[0]
    loop = QEventLoop()
    QTimer.singleShot(3000, loop.quit)
    loop.exec()
    shot = window.grabWindow().convertToFormat(QImage.Format.Format_RGBA8888)
    shot.save(str(image))
    pixels = np.frombuffer(shot.constBits(), np.uint8)[:shot.height() * shot.bytesPerLine()]
    rgb = pixels.reshape(shot.height(), shot.bytesPerLine())[:, :shot.width() * 4].reshape(
        shot.height(), shot.width(), 4)[..., :3].astype(int)
    yellow = float(np.mean((rgb[..., 0] > 120) & (rgb[..., 1] > 80) & (rgb[..., 2] < 0.6 * rgb[..., 1])))
    api = window.rendererInterface().graphicsApi().name if hasattr(window, "rendererInterface") else "?"
    report.append(f"rendu : {api}, {shot.width()}×{shot.height()}, feuillage {yellow * 100:.1f} % de l'image")
    report.extend(f"avertissement : {text}" for text in problems)
    del engine, app
    return done(0 if yellow > 0.03 and not problems else 1)


def _garden_check(engine) -> list[str]:
    """The garden (Qt Quick 3D, its shaders, the tree) and the listening card (Qt Multimedia) are
    shown only during and after a mix: built here, so that a missing module fails the check."""
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlComponent

    from eden.gui.app import QML_DIR
    from eden.gui.garden import grow_tree

    errors = []
    for name in ("GardenScene", "GardenView", "ListenCard"):
        component = QQmlComponent(engine, QUrl.fromLocalFile(str(QML_DIR / f"{name}.qml")))
        made = component.create()
        if made is None:
            errors += [f"{name} : {e.toString()}" for e in component.errors()] or [f"{name} : non créé"]
        else:
            made.deleteLater()
    tree = grow_tree()
    if len(tree.leaf_pos) < 500 or tree.heights[-1] < 3:
        errors.append("arbre du jardin incomplet")
    return errors


def _audio_check() -> str:
    """The bundled audio decoder and the mixing maths must work in the installed app."""
    import tempfile

    import numpy as np
    import soundfile as sf

    from eden.mix.loudness import integrated_loudness

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.wav"
        sf.write(path, np.zeros((480, 2), dtype=np.float32), 48000, subtype="FLOAT")
        data, sr = sf.read(path)
        if sr != 48000 or data.shape != (480, 2):
            raise RuntimeError("lecture/écriture WAV incorrecte")
    tone = np.sin(2 * np.pi * 997 * np.arange(48000 * 3) / 48000)
    lufs = integrated_loudness(tone, 48000)
    if abs(lufs + 3.01) > 0.05:
        raise RuntimeError(f"mesure de volume incorrecte ({lufs:.2f} LUFS)")
    # the whole mastering chain (filters, oversampling, soft clip, limiter) on a short signal
    # whose clicks need limiting
    from eden.mix.master import master

    clicks = np.zeros(tone.size)
    clicks[::12000] = 0.5
    signal = 0.1 * tone + clicks
    result = master(np.stack([signal, signal], axis=1), 48000, 1.0, 120.0)
    if result.limiter_db <= 0 and result.clip_db <= 0:
        raise RuntimeError("mastering : ni écrêtage ni limiteur sur des clics")
    ceiling = result.treatments[-1].measured["ceiling_dbtp"]
    if result.checks.true_peak_dbtp > ceiling + 0.05:
        raise RuntimeError(f"mastering incorrect (crête {result.checks.true_peak_dbtp:.2f} dBTP)")
    return (f"audio : libsndfile {sf.__libsndfile_version__}, mesure de volume {lufs:.2f} LUFS, "
            f"mastering {result.checks.integrated_lufs:.1f} LUFS / {result.checks.true_peak_dbtp:.1f} dBTP")


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--self-test":
        return self_test(Path(sys.argv[2]))
    if len(sys.argv) >= 3 and sys.argv[1] == "--render-test":
        return render_test(Path(sys.argv[2]))
    log_file = _setup_logging()
    logging.info("Démarrage d'Eden")
    try:
        from eden.gui.app import run

        return run()
    except Exception:
        logging.exception("Eden n'a pas pu démarrer")
        _show_fatal(log_file)
        return 1


def _show_fatal(log_file: Path) -> None:
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None, f"Eden n'a pas pu démarrer.\nDétails : {log_file}", "Eden", 0x10)
        except (AttributeError, OSError):
            pass


if __name__ == "__main__":
    raise SystemExit(main())
