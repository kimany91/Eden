"""Drive FL Studio to render Eden's working copies.

FL Studio is launched as a separate process on a *copy* of the project that
lives in Eden's workspace. The exact command-line syntax of FL Studio's
renderer is not documented in a place Eden can rely on, so it is not
hard-coded: ``eden fl-probe`` tries the known candidate syntaxes on the
user's machine and stores the one that really produces audio.

Starting FL Studio and its plugins is a good part of each render, so one FL
renders every copy in one launch (FL's render of a whole folder, documented by
Image-Line); a second one beside it only on a PC with the processor and memory
for it, and FL always runs at a low priority, so the PC stays smooth. Neither
is assumed to work: each WAV is checked by name, a copy left without one is
rendered again alone, and what worked on this PC is kept in the settings.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from eden.render import hidden_desktop
from eden.settings import load_settings, save_settings

# Syntaxes reported by FL Studio users; none is assumed to work until probed.
CANDIDATE_ARGS: list[tuple[str, list[str]]] = [
    ("rendu d'un projet en WAV", ["/R", "/Ewav", "{project}"]),
    ("rendu d'un dossier de projets en WAV", ["/R", "/Ewav", "/F{folder}"]),
]

FL_PROCESS_NAMES = ("FL64.exe", "FL.exe")
SW_SHOWMINNOACTIVE = 7  # Windows: start minimized, without taking the focus
MAX_SIDE_BY_SIDE = 2  # FL Studios rendering at once, at most: one already renders every copy
THREADS_PER_FL = 4  # FL already spreads one render over several processor threads
GB_PER_FL = 2.0  # memory one FL Studio takes to render a project with its plugins, with room to spare
WATCH_S = 1.0  # how often Eden looks for the WAV files of the copies being rendered


class RenderError(RuntimeError):
    pass


def no_console() -> dict:
    """Windows: a command-line program started by Eden (a window-less app) opens no console."""
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def out_of_the_way() -> dict:
    """Windows: FL Studio started for a render opens no console, runs at a low priority (what the user
    does on the PC goes first, nothing lags), and its window starts minimized without taking the focus,
    so nothing comes over Eden. FL Studio's windows are Delphi forms, which start minimized when asked
    this way; a dialog it shows (a plugin missing...) still appears, and a render it blocks ends with
    the timeout's message."""
    if os.name != "nt":
        return {}
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = SW_SHOWMINNOACTIVE
    return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS,
            "startupinfo": info}


Rendered = Callable[[Path, Path], None]  # (copy, its WAV)


class Renderer(Protocol):
    name: str

    def render(self, project_copy: Path, timeout_s: float) -> Path:
        """Render ``project_copy`` and return the produced WAV file."""

    def render_many(self, copies: list[Path], timeout_s: float, on_rendered: Rendered) -> None:
        """Render ``copies`` (each one alone in its folder) the fastest way, telling ``on_rendered`` the WAV
        of each one as soon as it is there; a copy not told of is left for ``render``."""


def _free_memory_gb() -> float | None:
    """Memory free for programs right now (Windows); None where it is not known."""
    if os.name != "nt":
        return None
    import ctypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    *((n, ctypes.c_ulonglong) for n in ("ullTotalPhys", "ullAvailPhys", "ullTotalPageFile",
                                                        "ullAvailPageFile", "ullTotalVirtual", "ullAvailVirtual",
                                                        "ullAvailExtendedVirtual"))]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return status.ullAvailPhys / 2 ** 30


def side_by_side_count(copies: int) -> int:
    """How many FL Studios render at once on this PC: one per THREADS_PER_FL processor threads, each with
    GB_PER_FL of free memory, at most MAX_SIDE_BY_SIDE, and never more than there are copies."""
    count = min(MAX_SIDE_BY_SIDE, copies, (os.cpu_count() or 1) // THREADS_PER_FL)
    free = _free_memory_gb()
    if free is not None:
        count = min(count, int(free // GB_PER_FL))
    return max(1, count)


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


def _wav_files(folder: Path) -> dict[Path, os.stat_result]:
    """The WAV files under ``folder`` (one can go meanwhile: Eden takes each one FL has finished)."""
    found = {}
    for p in folder.rglob("*.wav"):
        try:
            found[p] = p.stat()
        except OSError:
            continue
    return found


def _wav_snapshot(folder: Path) -> dict[Path, float]:
    return {p: st.st_mtime for p, st in _wav_files(folder).items()}


def _wav_sizes(folder: Path) -> dict[Path, int]:
    """What a render has written so far (the files grow while FL renders)."""
    return {p: st.st_size for p, st in _wav_files(folder).items()}


def _new_outputs(folder: Path, before: dict[Path, float]) -> list[Path]:
    """WAV files a render wrote, the largest first."""
    after = _wav_files(folder)
    return sorted((p for p, st in after.items() if p not in before or before[p] != st.st_mtime),
                  key=lambda p: after[p].st_size, reverse=True)


@dataclass
class RunOutcome:
    returncode: int | None
    timed_out: bool
    seconds: float
    outputs: list[Path]
    stderr: str
    dialog: str | None = None  # what FL Studio was asking (title and text of its message) when it was closed
    hidden: bool = False  # FL ran on a desktop of its own

    @property
    def ended_by_itself(self) -> bool:
        """FL Studio closed on its own: every file it wrote is finished."""
        return not (self.timed_out or self.dialog)


@dataclass
class _Launch:
    """One launch of FL Studio by ``render_many``: the copies it renders (where they are while it does →
    where they came from), those whose WAV Eden has taken, and how FL ended."""
    folder: Path
    copies: dict[Path, Path]
    told: set[Path] = field(default_factory=set)
    outcome: RunOutcome | None = None  # None while it runs, or when FL could not even start


# whether FL Studio renders on a desktop of its own on this PC: unknown until a render says
_hidden_renders: bool | None = None


class FLStudioRenderer:
    """Render through FL Studio's command line.

    ``command`` is the program to start: ``[path_to_FL64.exe]`` normally,
    or another argv prefix (tests use a simulator script).
    """

    def __init__(self, command: list[str], args_template: list[str], name: str = "FL Studio",
                 side_by_side: bool | None = None, folders: bool | None = None,
                 on_learned: Callable[[FLStudioRenderer], None] | None = None) -> None:
        self.command = command
        self.args_template = args_template
        self.name = name
        # learned from the renders on this PC (None until tried), handed to ``on_learned`` to be kept
        self.side_by_side = side_by_side  # several FL Studios render at once
        self.folders = folders  # one FL Studio renders a whole folder of copies in one launch
        self.on_learned = on_learned

    def build_args(self, project_copy: Path) -> list[str]:
        values = {"project": str(project_copy), "folder": str(project_copy.parent)}
        return [*self.command, *(a.format(**values) for a in self.args_template)]

    def folder_args(self) -> list[str] | None:
        """The command for a whole folder of copies: the one that works, its project read as a folder."""
        if "{project}" in self.args_template:
            return ["/F{folder}" if a == "{project}" else a for a in self.args_template]
        return self.args_template if any("{folder}" in a for a in self.args_template) else None

    def run(self, project_copy: Path, timeout_s: float) -> RunOutcome:
        return self._launch(self.build_args(project_copy), project_copy.parent, timeout_s)

    def _launch(self, args: list[str], folder: Path, timeout_s: float, shown_if_nothing: bool = True) -> RunOutcome:
        """FL Studio on a desktop of its own that is never shown (Windows, ``hidden_desktop``), so
        nothing of it comes over Eden; started the usual way where that desktop is refused, or
        (``shown_if_nothing``) when FL renders nothing there and never has."""
        global _hidden_renders
        if hidden_desktop.available() and _hidden_renders is not False:
            try:
                outcome = self._run_hidden(args, folder, timeout_s)
            except hidden_desktop.Unavailable:
                _hidden_renders = False
            else:
                if outcome.outputs:
                    _hidden_renders = True
                if outcome.outputs or outcome.timed_out or outcome.dialog or _hidden_renders or not shown_if_nothing:
                    return outcome
                shown = self._run_shown(args, folder, timeout_s)  # nothing at all: tried once shown
                if shown.outputs:  # FL renders when shown, not on a desktop of its own: shown from now on
                    _hidden_renders = False
                return shown
        return self._run_shown(args, folder, timeout_s)

    def _run_hidden(self, args: list[str], folder: Path, timeout_s: float) -> RunOutcome:
        before = _wav_snapshot(folder)
        start = time.monotonic()
        try:
            run = hidden_desktop.run_hidden(args, folder, timeout_s, lambda: _wav_sizes(folder))
        except hidden_desktop.Unavailable:
            raise
        except OSError as exc:
            raise RenderError(f"Impossible de lancer FL Studio ({exc})") from exc
        return RunOutcome(run.returncode, run.timed_out, time.monotonic() - start, _new_outputs(folder, before),
                          "", run.dialog, hidden=True)

    def _run_shown(self, args: list[str], folder: Path, timeout_s: float) -> RunOutcome:
        before = _wav_snapshot(folder)
        start = time.monotonic()
        try:
            proc = subprocess.Popen(args, cwd=folder,
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
        return RunOutcome(proc.returncode, timed_out, time.monotonic() - start, _new_outputs(folder, before),
                          (err or b"").decode("utf-8", errors="replace")[-2000:])

    def render(self, project_copy: Path, timeout_s: float) -> Path:
        outcome = self.run(project_copy, timeout_s)
        if outcome.dialog:
            raise RenderError(f"FL Studio attend une réponse : « {outcome.dialog} ». Ouvre le projet dans "
                              "FL Studio pour voir ce qu'il demande, règle-le, puis relance")
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

    def render_many(self, copies: list[Path], timeout_s: float, on_rendered: Rendered) -> None:
        """Render ``copies`` (each one alone in its folder) with as few launches of FL Studio as it takes.

        One FL renders them all in one launch (FL's render of a whole folder): FL and its plugins start
        once, not once per copy. On a PC with the processor and memory for it, the copies are shared out
        between two FL Studios rendering side by side, each on its own desktop. ``on_rendered`` is told
        each WAV, by its copy's name, as soon as FL has finished it (FL renders a folder one copy after
        another: each WAV but the last is done, the last one too once FL closed on its own). Where
        folders do not render here, the copies are launched one by one, two at a time. A copy left
        without its WAV (FL refused to start beside another, rendered nothing on its own desktop, a
        message stopped it...) is not told of: ``render`` renders it alone, the proven way (shown, if FL
        renders nothing on a desktop of its own), and says what goes wrong if it still does. What
        worked and what did not is kept (``on_learned``) so that the next renders go the right way."""
        count = side_by_side_count(len(copies)) if self.side_by_side is not False else 1
        folder_args = self.folder_args() if self.folders is not False and len(copies) > count else None
        if folder_args is None and count == 1:
            return  # one copy at a time is what ``render`` does
        if folder_args is None:
            launches = [_Launch(c.parent, {c: c}) for c in copies]
        else:
            work = Path(os.path.commonpath([c.parent for c in copies])) / "lots"
            shutil.rmtree(work, ignore_errors=True)  # left by a run that was stopped
            launches = [_Launch(work / f"lot-{k + 1}", {}) for k in range(count)]
            for k, launch in enumerate(launches):
                launch.folder.mkdir(parents=True)
                for c in copies[k::count]:
                    launch.copies[c.replace(launch.folder / c.name)] = c
        learned = (self.side_by_side, self.folders)
        try:
            self._render_launches(launches, folder_args, timeout_s, count, on_rendered)
        finally:
            if folder_args is not None:
                for launch in launches:
                    for there, copy in launch.copies.items():
                        if there not in launch.told and there.is_file():
                            there.replace(copy)  # back where it was, for ``render``
                shutil.rmtree(work, ignore_errors=True)
        self._learn(launches, folder_args is not None, count)
        if self.on_learned and (self.side_by_side, self.folders) != learned:
            self.on_learned(self)

    def _render_launches(self, launches: list[_Launch], folder_args: list[str] | None, timeout_s: float,
                         count: int, on_rendered: Rendered) -> None:
        def start(launch: _Launch) -> RunOutcome:  # never shown: ``render`` does that, alone
            if folder_args is None:
                (copy,) = launch.copies
                return self._launch(self.build_args(copy), copy.parent, timeout_s, shown_if_nothing=False)
            values = {"project": str(launch.folder), "folder": str(launch.folder)}
            return self._launch([*self.command, *(a.format(**values) for a in folder_args)], launch.folder,
                                timeout_s * len(launch.copies), shown_if_nothing=False)

        def finished_wavs(launch: _Launch) -> dict[Path, Path]:
            """Copy (where FL renders it) → its WAV, for the ones FL is done with and not yet told of."""
            done = launch.outcome is not None and launch.outcome.ended_by_itself
            if folder_args is None:
                if not (done and launch.outcome.outputs):
                    return {}
                return {there: launch.outcome.outputs[0] for there in launch.copies}
            found = _wav_files(launch.folder)
            wavs = sorted((wav for wav in (there.with_suffix(".wav") for there in launch.copies) if wav in found),
                          key=lambda wav: found[wav].st_mtime)
            if not done:
                wavs = wavs[:-1]  # the one FL may still be writing, or was writing when it was closed
            return {wav.with_suffix(".flp"): wav for wav in wavs}

        with ThreadPoolExecutor(count) as pool:
            running: dict[Future, _Launch] = {pool.submit(start, launch): launch for launch in launches}
            while running:
                finished, _ = wait(running, timeout=WATCH_S, return_when=FIRST_COMPLETED)
                for future in finished:
                    launch = running.pop(future)
                    try:
                        launch.outcome = future.result()
                    except RenderError:  # FL could not even start: ``render`` says why
                        continue
                for launch in launches:
                    for there, wav in finished_wavs(launch).items():
                        if there not in launch.told:
                            launch.told.add(there)
                            on_rendered(launch.copies[there], wav)

    def _learn(self, launches: list[_Launch], folder_mode: bool, count: int) -> None:
        """What the launches say of this PC. A folder render that gave nothing while FL closed on its own
        does not work here; FL Studios side by side do not when one renders and another, closed on its
        own, gives nothing. A launch on a desktop of its own that gave nothing says something only once
        FL is known to render there."""
        rendered = [launch for launch in launches if launch.told]
        idle = [launch for launch in launches
                if not launch.told and launch.outcome is not None and launch.outcome.ended_by_itself
                and (not launch.outcome.hidden or _hidden_renders is True)]
        if folder_mode:
            if rendered:
                self.folders = True
            elif len(idle) == len(launches):
                self.folders = False
        if count > 1 and rendered:
            if len(rendered) == len(launches):
                self.side_by_side = True
            elif idle:
                self.side_by_side = False


def configured_renderer(settings_file: Path | None = None) -> FLStudioRenderer | None:
    """FL Studio renderer from the saved settings, or None if not set up yet. What it learns of how FL
    renders several copies on this PC is saved with them."""
    settings = load_settings(settings_file)
    exe = find_fl_studio(settings.fl_path)
    if exe is None or not settings.render_args:
        return None

    def keep(renderer: FLStudioRenderer) -> None:
        current = load_settings(settings_file)
        current.render_side_by_side, current.render_folders = renderer.side_by_side, renderer.folders
        save_settings(current, settings_file)

    return FLStudioRenderer([str(exe)], settings.render_args, side_by_side=settings.render_side_by_side,
                            folders=settings.render_folders, on_learned=keep)
