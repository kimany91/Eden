"""Drive FL Studio to render Eden's working copies.

FL Studio is launched as a separate process on a *copy* of the project that
lives in Eden's workspace. The exact command-line syntax of FL Studio's
renderer is not documented in a place Eden can rely on, so it is not
hard-coded: ``eden fl-probe`` tries the known candidate syntaxes on the
user's machine and stores the one that really produces audio.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# Syntaxes reported by FL Studio users; none is assumed to work until probed.
CANDIDATE_ARGS: list[tuple[str, list[str]]] = [
    ("rendu d'un projet en WAV", ["/R", "/Ewav", "{project}"]),
    ("rendu d'un dossier de projets en WAV", ["/R", "/Ewav", "/F{folder}"]),
]

FL_PROCESS_NAMES = ("FL64.exe", "FL.exe")
SW_SHOWMINNOACTIVE = 7  # Windows: start minimized, without taking the focus


class RenderError(RuntimeError):
    pass


def no_console() -> dict:
    """Windows: a command-line program started by Eden (a window-less app) opens no console."""
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def out_of_the_way() -> dict:
    """Windows: FL Studio started for a render opens no console, and its window starts minimized
    without taking the focus, so nothing comes over Eden. FL Studio's windows are Delphi forms,
    which start minimized when asked this way; a dialog it shows (a plugin missing...) still
    appears, and a render it blocks ends with the timeout's message."""
    if os.name != "nt":
        return {}
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = SW_SHOWMINNOACTIVE
    return {**no_console(), "startupinfo": info}


class Renderer(Protocol):
    name: str

    def render(self, project_copy: Path, timeout_s: float) -> Path:
        """Render ``project_copy`` and return the produced WAV file."""


def find_fl_studio(configured: str | None = None) -> Path | None:
    """Locate FL64.exe: configured path, EDEN_FL_PATH, then Program Files."""
    for candidate in (configured, os.environ.get("EDEN_FL_PATH")):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    found: list[Path] = []
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        base = os.environ.get(var)
        if not base:
            continue
        il = Path(base) / "Image-Line"
        if not il.is_dir():
            continue
        for folder in il.glob("FL Studio*"):
            for exe in ("FL64.exe", "FL.exe"):
                if (folder / exe).is_file():
                    found.append(folder / exe)
                    break
    if not found:
        return None
    return max(found, key=lambda p: p.stat().st_mtime)  # most recently installed


def fl_is_running() -> bool | None:
    """True/False on Windows, None when it cannot be determined."""
    if os.name != "nt":
        return None
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True,
                             text=True, timeout=20, **no_console()).stdout.lower()
    except (OSError, subprocess.SubprocessError):
        return None
    return any(f'"{name.lower()}"' in out for name in FL_PROCESS_NAMES)


def _wav_snapshot(folder: Path) -> dict[Path, float]:
    return {p: p.stat().st_mtime for p in folder.rglob("*.wav")}


@dataclass
class RunOutcome:
    returncode: int | None
    timed_out: bool
    seconds: float
    outputs: list[Path]
    stderr: str


class FLStudioRenderer:
    """Render through FL Studio's command line.

    ``command`` is the program to start: ``[path_to_FL64.exe]`` normally,
    or another argv prefix (tests use a simulator script).
    """

    def __init__(self, command: list[str], args_template: list[str], name: str = "FL Studio") -> None:
        self.command = command
        self.args_template = args_template
        self.name = name

    def build_args(self, project_copy: Path) -> list[str]:
        values = {"project": str(project_copy), "folder": str(project_copy.parent)}
        return [*self.command, *(a.format(**values) for a in self.args_template)]

    def run(self, project_copy: Path, timeout_s: float) -> RunOutcome:
        folder = project_copy.parent
        before = _wav_snapshot(folder)
        start = time.monotonic()
        try:
            proc = subprocess.Popen(self.build_args(project_copy), cwd=folder,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                    **out_of_the_way())
        except OSError as exc:
            raise RenderError(f"Impossible de lancer FL Studio ({exc})") from exc
        timed_out = False
        try:
            _, err = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            _, err = proc.communicate()
        after = _wav_snapshot(folder)
        outputs = sorted(
            (p for p, m in after.items() if p not in before or before[p] != m),
            key=lambda p: p.stat().st_size, reverse=True,
        )
        return RunOutcome(proc.returncode, timed_out, time.monotonic() - start, outputs,
                          (err or b"").decode("utf-8", errors="replace")[-2000:])

    def render(self, project_copy: Path, timeout_s: float) -> Path:
        outcome = self.run(project_copy, timeout_s)
        if outcome.timed_out and not outcome.outputs:
            raise RenderError(
                f"FL Studio n'a pas terminé en {timeout_s:.0f} s (une fenêtre de dialogue "
                "bloque peut-être le rendu : plugin manquant, fichier introuvable…)"
            )
        if not outcome.outputs:
            raise RenderError(
                f"FL Studio s'est arrêté (code {outcome.returncode}) sans produire de fichier WAV"
            )
        return outcome.outputs[0]
