"""Drive FL Studio to render Eden's working copies.

FL Studio is launched as a separate process on a *copy* of the project that
lives in Eden's workspace. The exact command-line syntax of FL Studio's
renderer is not documented in a place Eden can rely on, so it is not
hard-coded: ``eden fl-probe`` tries the known candidate syntaxes on the
user's machine and stores the one that really produces audio.

Several FL Studios render side by side, as many as the PC has processor
threads and free memory for, each one copy, the way FL renders on this PC; FL
always runs at a low priority, so the PC stays smooth. A copy left without its
WAV is rendered again alone, and whether FL Studios can render side by side
here is kept in the settings. An FL that stays open once its WAV is written is
closed by Eden.
"""

from __future__ import annotations

import os
import struct
import subprocess
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
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
MAX_SIDE_BY_SIDE = 8  # FL Studios rendering at once, at most
THREADS_PER_FL = 2  # processor threads one FL Studio renders on, roughly
GB_PER_FL = 1.5  # memory one FL Studio takes to render a project with its plugins, with room to spare
GB_KEPT_FREE = 2.0  # memory left to Windows and the user's programs
DONE_GRACE_S = 20.0  # an FL whose WAV is written and unchanged this long, still open, is closed by Eden


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

    def at_once(self, copies: int) -> int:
        """How many of ``copies`` are rendered at the same time."""

    def render_many(self, copies: list[Path], timeout_s: float, on_rendered: Rendered) -> None:
        """Render ``copies`` (each one alone in its folder) several at a time, telling ``on_rendered`` the
        WAV of each one as soon as it is there; a copy not told of is left for ``render``."""


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
    GB_PER_FL of free memory once GB_KEPT_FREE is left to the rest, at most MAX_SIDE_BY_SIDE, and never more
    than there are copies."""
    count = min(MAX_SIDE_BY_SIDE, copies, (os.cpu_count() or 1) // THREADS_PER_FL)
    free = _free_memory_gb()
    if free is not None:
        count = min(count, int((free - GB_KEPT_FREE) // GB_PER_FL))
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
    """The WAV files under ``folder`` (one can go while they are listed)."""
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


def _written(wav: Path) -> int | None:
    """Size of a WAV file whose header gives its full size (a writer fills it in once the file is
    written), None while it is not, or not readable yet."""
    try:
        with wav.open("rb") as f:
            head = f.read(12)
        size = wav.stat().st_size
    except OSError:
        return None
    if len(head) < 12 or head[:4] != b"RIFF" or head[8:] != b"WAVE" or struct.unpack("<I", head[4:8])[0] + 8 != size:
        return None
    return size


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
    done: Path | None = None  # the copy's WAV, written, when FL stayed open after it and Eden closed it

    @property
    def wav(self) -> Path | None:
        """The WAV this render produced, when FL ended well (on its own, or closed once it was written)."""
        if self.done is not None:
            return self.done
        return self.outputs[0] if self.outputs and not (self.timed_out or self.dialog) else None


# whether FL Studio renders on a desktop of its own on this PC: unknown until a render says
_hidden_renders: bool | None = None


class FLStudioRenderer:
    """Render through FL Studio's command line.

    ``command`` is the program to start: ``[path_to_FL64.exe]`` normally,
    or another argv prefix (tests use a simulator script).
    """

    def __init__(self, command: list[str], args_template: list[str], name: str = "FL Studio",
                 side_by_side: bool | None = None,
                 on_learned: Callable[[FLStudioRenderer], None] | None = None) -> None:
        self.command = command
        self.args_template = args_template
        self.name = name
        # whether several FL Studios render at once on this PC (None until tried), handed to ``on_learned``
        self.side_by_side = side_by_side
        self.on_learned = on_learned

    def build_args(self, project_copy: Path) -> list[str]:
        values = {"project": str(project_copy), "folder": str(project_copy.parent)}
        return [*self.command, *(a.format(**values) for a in self.args_template)]

    def run(self, project_copy: Path, timeout_s: float, shown_if_nothing: bool = True) -> RunOutcome:
        """FL Studio on a desktop of its own that is never shown (Windows, ``hidden_desktop``), so
        nothing of it comes over Eden; started the usual way where that desktop is refused, or
        (``shown_if_nothing``) when FL renders nothing there and never has. FL names its WAV after the
        copy: once that file is written and FL still has not closed DONE_GRACE_S later, Eden closes it."""
        global _hidden_renders
        args, folder, wav = self.build_args(project_copy), project_copy.parent, project_copy.with_suffix(".wav")
        if hidden_desktop.available() and _hidden_renders is not False:
            try:
                outcome = self._run_hidden(args, folder, wav, timeout_s)
            except hidden_desktop.Unavailable:
                _hidden_renders = False
            else:
                if outcome.outputs or outcome.done:
                    _hidden_renders = True
                if outcome.outputs or outcome.done or outcome.timed_out or outcome.dialog or _hidden_renders \
                        or not shown_if_nothing:
                    return outcome
                shown = self._run_shown(args, folder, wav, timeout_s)  # nothing at all: tried once shown
                if shown.outputs or shown.done:  # FL renders when shown, not on a desktop of its own
                    _hidden_renders = False
                return shown
        return self._run_shown(args, folder, wav, timeout_s)

    @staticmethod
    def _written_and_left(wav: Path, before: dict[Path, float]) -> Callable[[], bool]:
        """Whether this render wrote ``wav`` (not the one a previous render left), its header giving its size,
        and has left it unchanged for DONE_GRACE_S."""
        seen, seen_at = None, 0.0

        def done() -> bool:
            nonlocal seen, seen_at
            size = _written(wav)
            try:
                written = size is not None and wav.stat().st_mtime != before.get(wav)
            except OSError:
                written = False
            if not written or size != seen:
                seen, seen_at = size if written else None, time.monotonic()
                return False
            return time.monotonic() - seen_at >= DONE_GRACE_S

        return done

    def _run_hidden(self, args: list[str], folder: Path, wav: Path, timeout_s: float) -> RunOutcome:
        before = _wav_snapshot(folder)
        start = time.monotonic()
        try:
            run = hidden_desktop.run_hidden(args, folder, timeout_s, lambda: _wav_sizes(folder),
                                            self._written_and_left(wav, before))
        except hidden_desktop.Unavailable:
            raise
        except OSError as exc:
            raise RenderError(f"Impossible de lancer FL Studio ({exc})") from exc
        return RunOutcome(run.returncode, run.timed_out, time.monotonic() - start, _new_outputs(folder, before),
                          "", run.dialog, hidden=True, done=wav if run.done else None)

    def _run_shown(self, args: list[str], folder: Path, wav: Path, timeout_s: float) -> RunOutcome:
        before = _wav_snapshot(folder)
        start = time.monotonic()
        try:
            proc = subprocess.Popen(args, cwd=folder,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                    **out_of_the_way())
        except OSError as exc:
            raise RenderError(f"Impossible de lancer FL Studio ({exc})") from exc
        deadline, written = time.monotonic() + timeout_s, self._written_and_left(wav, before)
        timed_out = done = False
        while True:
            try:
                _, err = proc.communicate(timeout=hidden_desktop.POLL_S)
                break
            except subprocess.TimeoutExpired:
                done = written()
                timed_out = not done and time.monotonic() >= deadline
                if done or timed_out:
                    proc.kill()
                    _, err = proc.communicate()
                    break
        return RunOutcome(proc.returncode, timed_out, time.monotonic() - start, _new_outputs(folder, before),
                          (err or b"").decode("utf-8", errors="replace")[-2000:], done=wav if done else None)

    def render(self, project_copy: Path, timeout_s: float) -> Path:
        outcome = self.run(project_copy, timeout_s)
        if outcome.done:
            return outcome.done
        if outcome.dialog:
            raise RenderError(f"FL Studio attend une réponse : « {outcome.dialog} ». Ouvre le projet dans "
                              "FL Studio pour voir ce qu'il demande, règle-le, puis relance")
        if outcome.timed_out:  # what it wrote may be cut short
            raise RenderError(
                f"FL Studio n'a pas terminé en {timeout_s:.0f} s (une fenêtre de dialogue "
                "bloque peut-être le rendu : plugin manquant, fichier introuvable…)"
            )
        if not outcome.outputs:
            raise RenderError(
                f"FL Studio s'est arrêté (code {outcome.returncode}) sans produire de fichier WAV"
            )
        return outcome.outputs[0]

    def at_once(self, copies: int) -> int:
        return side_by_side_count(copies) if self.side_by_side is not False else 1

    def render_many(self, copies: list[Path], timeout_s: float, on_rendered: Rendered) -> None:
        """Render ``copies`` (each one alone in its folder) several at a time: as many FL Studios side by
        side as this PC has room for (``side_by_side_count``), each rendering one copy the way ``run``
        does, on its own desktop and at a low priority. ``on_rendered`` is told each WAV as soon as its
        FL is done. A copy left without one (FL refused to start beside another, a message stopped it...)
        is not told of: ``render`` renders it alone, the proven way (shown, if FL renders nothing on a
        desktop of its own), and says what goes wrong if it still does. Whether FL Studios render side by
        side here is learned and kept (``on_learned``): not when some render and others, closed on their
        own, give nothing (on their own desktop, once FL is known to render there)."""
        count = self.at_once(len(copies))
        if count == 1:
            return  # one copy at a time is what ``render`` does
        rendered, idle = 0, 0
        with ThreadPoolExecutor(count) as pool:
            launches = {pool.submit(self.run, copy, timeout_s, False): copy for copy in copies}
            for launch in as_completed(launches):
                try:
                    outcome = launch.result()
                except RenderError:  # FL could not even start: ``render`` says why
                    continue
                if outcome.wav is not None:
                    rendered += 1
                    on_rendered(launches[launch], outcome.wav)
                elif not (outcome.timed_out or outcome.dialog) and (not outcome.hidden or _hidden_renders):
                    idle += 1
        learned = self.side_by_side
        if rendered:
            self.side_by_side = not idle
        if self.on_learned and self.side_by_side != learned:
            self.on_learned(self)


def configured_renderer(settings_file: Path | None = None) -> FLStudioRenderer | None:
    """FL Studio renderer from the saved settings, or None if not set up yet. Whether FL Studios render
    side by side on this PC, once it has learned it, is saved with them."""
    settings = load_settings(settings_file)
    exe = find_fl_studio(settings.fl_path)
    if exe is None or not settings.render_args:
        return None

    def keep(renderer: FLStudioRenderer) -> None:
        current = load_settings(settings_file)
        current.render_side_by_side = renderer.side_by_side
        save_settings(current, settings_file)

    return FLStudioRenderer([str(exe)], settings.render_args, side_by_side=settings.render_side_by_side,
                            on_learned=keep)
