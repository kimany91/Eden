# PyInstaller recipe: builds dist/Eden/ (Eden.exe + everything it needs, no Python required).
# Run from the repository root:  pyinstaller packaging/eden.spec --noconfirm
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent
ICON = ROOT / "src" / "eden" / "assets" / "eden.ico"

a = Analysis(
    [str(ROOT / "packaging" / "eden_main.py")],
    pathex=[str(ROOT / "src")],
    datas=collect_data_files("eden", includes=["assets/*", "gui/qml/*"]),
    hiddenimports=[
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickControls2", "PySide6.QtSvg",
        "eden.gui.app", "eden.gui.controller", "eden.render.probe",
    ],
    excludes=["tkinter", "matplotlib", "scipy", "PIL", "pytest", "PyInstaller"],
    noarchive=False,
)
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
