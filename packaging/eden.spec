# PyInstaller recipe: builds dist/Eden/ (Eden.exe + everything it needs, no Python required).
# Run from the repository root:  pyinstaller packaging/eden.spec --noconfirm
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent
ICON = ROOT / "src" / "eden" / "assets" / "eden.ico"

a = Analysis(
    [str(ROOT / "packaging" / "eden_main.py")],
    pathex=[str(ROOT / "src")],
    datas=collect_data_files("eden", includes=["assets/*", "gui/qml/*", "gui/qml/shaders/*"]),
    hiddenimports=[
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickControls2", "PySide6.QtSvg",
        "PySide6.QtQuick3D", "PySide6.QtMultimedia",
        "eden.gui.app", "eden.gui.controller", "eden.gui.garden_qml", "eden.gui.player", "eden.render.probe",
    ],
    excludes=["tkinter", "matplotlib", "PIL", "pytest", "PyInstaller"],
    noarchive=False,
)
# Qt's add-on modules (Qt Quick 3D, Qt Multimedia) come with many Eden does not use, and PyInstaller takes
# every QML module there is: their plugins and libraries stay out, as do the Quick Controls styles other
# than Basic (the one Eden draws on). The self-test of each built installer loads the whole interface,
# garden and listening card included: a module wrongly left out fails it before anything is published.
UNUSED_QML = ("Qt3D", "QtCharts", "QtDataVisualization", "QtGraphs", "QtLocation", "QtPositioning",
              "QtTextToSpeech", "QtSensors", "QtScxml", "QtRemoteObjects", "QtWebChannel", "QtWebSockets",
              "QtWebView", "QtTest", "QtWayland", "QtQuick3D/Physics", "QtQuick3D/Particles3D",
              "QtQuick3D/ParticleEffects", "QtQuick3D/Xr", "QtQuick3D/SpatialAudio", "QtQuick/VirtualKeyboard",
              "QtQuick/Controls/Imagine", "QtQuick/Controls/FluentWinUI3", "QtQuick/Controls/Material",
              "QtQuick/Controls/Universal", "QtQuick/Controls/Fusion")
UNUSED_LIBS = ("3D", "Charts", "DataVisualization", "Graphs", "Location", "Positioning", "TextToSpeech",
               "Sensors", "Scxml", "RemoteObjects", "WebChannel", "WebSockets", "WebView", "Test", "QuickTest",
               "Quick3DPhysics", "Quick3DParticles", "Quick3DParticleEffects", "Quick3DXr", "Quick3DSpatialAudio",
               "SpatialAudio", "VirtualKeyboard", "Wayland", "QuickControls2Imagine", "QuickControls2FluentWinUI3",
               "QuickControls2Material", "QuickControls2Universal", "QuickControls2Fusion")


def _used(entry) -> bool:
    path = entry[0].replace("\\", "/")
    if any(f"/qml/{name}/" in path for name in UNUSED_QML):
        return False
    name = path.rsplit("/", 1)[-1]
    stem = name[6:] if name.startswith("libQt6") else name[3:] if name.startswith("Qt6") else ""
    return not (stem and any(stem.startswith(lib) for lib in UNUSED_LIBS))


a.binaries = [b for b in a.binaries if _used(b)]
a.datas = [d for d in a.datas if _used(d)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Eden",
    console=False,
    icon=str(ICON),
    version=str(ROOT / "packaging" / "version_info.txt") if (ROOT / "packaging" / "version_info.txt").exists() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Eden")
