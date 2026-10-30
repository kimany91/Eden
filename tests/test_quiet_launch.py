"""Nothing comes over Eden and nothing lags: the programs it starts open no console window, FL Studio
runs at a low priority, and where it cannot have a desktop of its own it starts minimized without
taking the focus (render/fl_studio.py)."""

import os
import subprocess

import pytest

from eden.render import fl_studio
from eden.render.fl_studio import FLStudioRenderer, no_console, out_of_the_way

windows = pytest.mark.skipif(os.name != "nt", reason="Windows only")


@windows
def test_on_windows_a_command_line_program_opens_no_console():
    assert no_console() == {"creationflags": subprocess.CREATE_NO_WINDOW}


@windows
def test_on_windows_fl_studio_starts_minimized_without_taking_the_focus():
    kw = out_of_the_way()
    assert kw["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert kw["creationflags"] & subprocess.BELOW_NORMAL_PRIORITY_CLASS  # what the user does goes first
    info = kw["startupinfo"]
    assert info.dwFlags & subprocess.STARTF_USESHOWWINDOW and info.wShowWindow == fl_studio.SW_SHOWMINNOACTIVE == 7


def test_elsewhere_nothing_is_asked():
    if os.name != "nt":
        assert no_console() == {} and out_of_the_way() == {}


class _Done:
    returncode = 0

    def communicate(self, timeout=None):
        return b"", b""


def test_fl_studio_started_the_usual_way_stays_out_of_the_way(tmp_path, monkeypatch):
    # where it cannot have a desktop of its own (render/hidden_desktop.py)
    seen = []
    monkeypatch.setattr(fl_studio.subprocess, "Popen", lambda args, **kw: seen.append(kw) or _Done())
    (tmp_path / "copie.flp").write_bytes(b"FLhd")
    renderer = FLStudioRenderer(["FL64.exe"], ["/R", "/Ewav", "{project}"])
    renderer._run_shown(renderer.build_args(tmp_path / "copie.flp"), tmp_path, timeout_s=5)
    assert len(seen) == 1
    if os.name == "nt":
        assert seen[0]["creationflags"] & subprocess.CREATE_NO_WINDOW
        assert seen[0]["startupinfo"].wShowWindow == fl_studio.SW_SHOWMINNOACTIVE
    else:
        assert "startupinfo" not in seen[0] and "creationflags" not in seen[0]


@windows
def test_looking_for_a_running_fl_studio_opens_no_console(monkeypatch):
    seen = []

    def run(args, **kw):
        seen.append(kw)
        return subprocess.CompletedProcess(args, 0, stdout='"FL64.exe","1234"\n')

    monkeypatch.setattr(fl_studio.subprocess, "run", run)
    assert fl_studio.fl_is_running() is True
    assert seen[0]["creationflags"] & subprocess.CREATE_NO_WINDOW
