"""Eden's window: a Qt Quick (QML) interface driven by :class:`EdenController`."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QUrl
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from eden.gui.controller import ASSETS, EdenController

QML_DIR = Path(__file__).resolve().parent / "qml"


class QmlLoadError(RuntimeError):
    pass


def create_engine(controller: EdenController, play_splash: bool = True) -> QQmlApplicationEngine:
    QQuickStyle.setStyle("Basic")  # fully custom look, identical on every PC
    engine = QQmlApplicationEngine()
    warnings: list[str] = []
    engine.warnings.connect(lambda ws: warnings.extend(w.toString() for w in ws))
    engine.rootContext().setContextProperty("controller", controller)
    engine.setInitialProperties({"playSplash": play_splash})
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    if not engine.rootObjects():
        raise QmlLoadError("Interface illisible :\n" + "\n".join(warnings))
    engine.load_warnings = warnings  # kept for tests and diagnostics
    return engine


def _windows_taskbar_identity() -> None:
    """Show Eden's own icon in the Windows taskbar instead of Python's."""
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Eden.MixageVocal")
        except (AttributeError, OSError):
            pass


def run(argv: list[str] | None = None) -> int:
    _windows_taskbar_identity()
    app = QGuiApplication(argv or sys.argv)
    app.setApplicationName("Eden")
    app.setOrganizationName("Eden")
    app.setWindowIcon(QIcon(str(ASSETS / "eden.ico")))
    controller = EdenController()
    engine = create_engine(controller)
    code = app.exec()
    controller.shutdown()
    dispose(engine)
    return code


def dispose(engine: QQmlApplicationEngine) -> None:
    """Destroy the interface before the controller it reads from."""
    for root in engine.rootObjects():
        root.setProperty("visible", False)
        root.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
