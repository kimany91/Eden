"""Entry point of the installed Windows application (no console).

``Eden.exe``                      opens the interface
``Eden.exe --self-test <log>``    loads the whole interface off-screen and
                                  exits 0 if it works (used to check every
                                  installer before it is published)
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
