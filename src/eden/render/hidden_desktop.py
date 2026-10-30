"""FL Studio on a desktop of its own that is never shown (Windows).

FL Studio's logo and window come over Eden, even when asked to start minimized. Windows can give a
program a desktop of its own: its windows exist and work, they are just never on screen. FL renders
there. What it cannot do there is ask the user something: a message (a plugin missing, a file to
find...) would wait unseen until the timeout. So the hidden desktop is watched: a message window that
stays while no render file grows is read (title and text), FL is closed, and Eden says what FL asked.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

# message boxes and dialogs of Windows; the message forms of Delphi programs such as FL Studio
DIALOG_CLASSES = ("#32770", "TMessageForm")
DIALOG_PATIENCE_S = 15.0  # a message that stays this long while nothing is rendered is waiting for an answer
POLL_S = 0.5
GENERIC_ALL = 0x10000000
CREATE_NO_WINDOW = 0x08000000
WAIT_OBJECT_0 = 0


class Unavailable(OSError):
    """This PC refuses Eden a desktop of its own: FL Studio starts the usual way."""


@dataclass
class HiddenRun:
    returncode: int | None  # None when FL was closed (timeout, or a message waiting for an answer)
    timed_out: bool
    dialog: str | None  # what FL was asking when it was closed


def available() -> bool:
    return os.name == "nt"


def _api() -> SimpleNamespace:
    from ctypes import wintypes as w

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class StartupInfo(ctypes.Structure):
        _fields_ = [("cb", w.DWORD), ("lpReserved", w.LPWSTR), ("lpDesktop", w.LPWSTR), ("lpTitle", w.LPWSTR),
                    ("dwX", w.DWORD), ("dwY", w.DWORD), ("dwXSize", w.DWORD), ("dwYSize", w.DWORD),
                    ("dwXCountChars", w.DWORD), ("dwYCountChars", w.DWORD), ("dwFillAttribute", w.DWORD),
                    ("dwFlags", w.DWORD), ("wShowWindow", w.WORD), ("cbReserved2", w.WORD),
                    ("lpReserved2", ctypes.c_void_p), ("hStdInput", w.HANDLE), ("hStdOutput", w.HANDLE),
                    ("hStdError", w.HANDLE)]

    class ProcessInformation(ctypes.Structure):
        _fields_ = [("hProcess", w.HANDLE), ("hThread", w.HANDLE), ("dwProcessId", w.DWORD),
                    ("dwThreadId", w.DWORD)]

    enum_proc = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    user32.CreateDesktopW.argtypes = [w.LPCWSTR, w.LPCWSTR, ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.c_void_p]
    user32.CreateDesktopW.restype = w.HANDLE
    user32.CloseDesktop.argtypes = [w.HANDLE]
    user32.EnumDesktopWindows.argtypes = [w.HANDLE, enum_proc, w.LPARAM]
    user32.EnumChildWindows.argtypes = [w.HWND, enum_proc, w.LPARAM]
    user32.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [w.HWND]
    kernel32.CreateProcessW.argtypes = [w.LPCWSTR, w.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, w.BOOL, w.DWORD,
                                        ctypes.c_void_p, w.LPCWSTR, ctypes.POINTER(StartupInfo),
                                        ctypes.POINTER(ProcessInformation)]
    kernel32.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    kernel32.WaitForSingleObject.restype = w.DWORD
    kernel32.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    kernel32.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
    kernel32.CloseHandle.argtypes = [w.HANDLE]
    return SimpleNamespace(user32=user32, kernel32=kernel32, StartupInfo=StartupInfo,
                           ProcessInformation=ProcessInformation, enum_proc=enum_proc, DWORD=w.DWORD)


def _text(api: SimpleNamespace, getter, hwnd) -> str:
    buf = ctypes.create_unicode_buffer(512)
    getter(hwnd, buf, len(buf))
    return buf.value.strip()


def _dialog(api: SimpleNamespace, desktop) -> str | None:
    """Title and text of a message window shown on ``desktop``, if there is one."""
    found: list[str] = []

    def child(hwnd, _):
        cls = _text(api, api.user32.GetClassNameW, hwnd)
        text = _text(api, api.user32.GetWindowTextW, hwnd)
        if text and "button" not in cls.lower():  # its text, not its OK / Cancel
            found.append(text)
        return True

    def top(hwnd, _):
        if api.user32.IsWindowVisible(hwnd) and _text(api, api.user32.GetClassNameW, hwnd) in DIALOG_CLASSES:
            found.append(_text(api, api.user32.GetWindowTextW, hwnd))
            api.user32.EnumChildWindows(hwnd, api.enum_proc(child), 0)
            return False  # one is enough
        return True

    api.user32.EnumDesktopWindows(desktop, api.enum_proc(top), 0)
    return " — ".join(t for t in found if t) or ("(sans texte)" if found else None)


def run_hidden(args: list[str], cwd: Path, timeout_s: float, progress: Callable[[], object]) -> HiddenRun:
    """Run ``args`` on a desktop never shown, until it ends, ``timeout_s`` passes, or a message stays
    ``DIALOG_PATIENCE_S`` while ``progress()`` (what the run has produced so far) does not change."""
    api = _api()
    name = f"Eden-{os.getpid()}-{time.monotonic_ns()}"
    desktop = api.user32.CreateDesktopW(name, None, None, 0, GENERIC_ALL, None)
    if not desktop:
        raise Unavailable(ctypes.get_last_error(), "CreateDesktopW")
    info, proc = api.StartupInfo(), api.ProcessInformation()
    info.cb = ctypes.sizeof(info)
    info.lpDesktop = name
    command = ctypes.create_unicode_buffer(subprocess.list2cmdline(args))
    try:
        if not api.kernel32.CreateProcessW(None, command, None, None, False, CREATE_NO_WINDOW, None, str(cwd),
                                           ctypes.byref(info), ctypes.byref(proc)):
            raise OSError(ctypes.get_last_error(), "CreateProcessW")
        api.kernel32.CloseHandle(proc.hThread)
        try:
            return _watch(api, desktop, proc.hProcess, timeout_s, progress)
        finally:
            api.kernel32.CloseHandle(proc.hProcess)
    finally:
        api.user32.CloseDesktop(desktop)


def _watch(api: SimpleNamespace, desktop, process, timeout_s: float, progress: Callable[[], object]) -> HiddenRun:
    deadline = time.monotonic() + timeout_s
    asking_since, produced = None, None
    while api.kernel32.WaitForSingleObject(process, int(POLL_S * 1000)) != WAIT_OBJECT_0:
        now = time.monotonic()
        if now >= deadline:
            return _close(api, process, HiddenRun(None, True, None))
        asking = _dialog(api, desktop)
        if asking is None:
            asking_since = None
            continue
        now_produced = progress()
        if asking_since is None or now_produced != produced:  # a message, but the render goes on
            asking_since, produced = now, now_produced
        elif now - asking_since >= DIALOG_PATIENCE_S:
            return _close(api, process, HiddenRun(None, False, asking))
    code = api.DWORD()
    api.kernel32.GetExitCodeProcess(process, ctypes.byref(code))
    return HiddenRun(int(code.value), False, None)


def _close(api: SimpleNamespace, process, run: HiddenRun) -> HiddenRun:
    api.kernel32.TerminateProcess(process, 1)
    api.kernel32.WaitForSingleObject(process, 10_000)
    return run
