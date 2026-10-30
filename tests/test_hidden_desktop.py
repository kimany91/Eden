"""FL Studio on a desktop of its own that is never shown (render/hidden_desktop.py): nothing of it comes
over Eden; a message it shows there is read and said instead of waited for; and where that desktop is
refused, or FL renders nothing there, it starts the usual way."""

import os
import sys
import textwrap
import threading
import time

import pytest

from eden.render import fl_studio, hidden_desktop
from eden.render.fl_studio import FLStudioRenderer, RenderError, RunOutcome

windows = pytest.mark.skipif(os.name != "nt", reason="Windows only")


# -- which way FL Studio is started (any system: the desktop is stood in for) ------------------------

@pytest.fixture
def launch(tmp_path, monkeypatch):
    """A renderer whose hidden runs follow ``hidden`` (what to do) and whose shown runs are counted."""
    monkeypatch.setattr(fl_studio, "_hidden_renders", None)
    monkeypatch.setattr(hidden_desktop, "available", lambda: True)
    calls = {"hidden": 0, "shown": 0}
    behaviour = {"hidden": "render", "shown": "render"}

    def hidden_run(args, cwd, timeout_s, progress):
        calls["hidden"] += 1
        what = behaviour["hidden"]
        if what == "refused":
            raise hidden_desktop.Unavailable(5, "CreateDesktopW")
        if what == "render":
            (cwd / f"rendu-{calls['hidden']}.wav").write_bytes(b"RIFF")
        return hidden_desktop.HiddenRun(None if what == "ask" else 0, False,
                                        "FL Studio — Plugin introuvable : Serum" if what == "ask" else None)

    def shown_run(self, args, folder, timeout_s):
        calls["shown"] += 1
        outputs = []
        if behaviour["shown"] == "render":
            out = folder / f"affiche-{calls['shown']}.wav"
            out.write_bytes(b"RIFF")
            outputs = [out]
        return RunOutcome(0, False, 0.1, outputs, "")

    monkeypatch.setattr(hidden_desktop, "run_hidden", hidden_run)
    monkeypatch.setattr(FLStudioRenderer, "_run_shown", shown_run)
    copy = tmp_path / "copie.flp"
    copy.write_bytes(b"FLhd")
    return FLStudioRenderer(["FL64.exe"], ["/R", "/Ewav", "{project}"]), copy, calls, behaviour


def test_fl_studio_renders_on_a_desktop_of_its_own(launch):
    renderer, copy, calls, _ = launch
    assert renderer.render(copy, 60).name == "rendu-1.wav"
    renderer.render(copy, 60)
    assert calls == {"hidden": 2, "shown": 0} and fl_studio._hidden_renders is True


def test_where_that_desktop_is_refused_fl_studio_starts_the_usual_way(launch):
    renderer, copy, calls, behaviour = launch
    behaviour["hidden"] = "refused"
    renderer.render(copy, 60)
    renderer.render(copy, 60)
    assert calls == {"hidden": 1, "shown": 2}  # asked once only


def test_when_fl_renders_nothing_there_but_renders_shown_it_is_shown_from_then_on(launch):
    renderer, copy, calls, behaviour = launch
    behaviour["hidden"] = "nothing"
    assert renderer.render(copy, 60).name == "affiche-1.wav"
    renderer.render(copy, 60)
    assert calls == {"hidden": 1, "shown": 2} and fl_studio._hidden_renders is False


def test_a_wrong_syntax_does_not_count_against_the_hidden_desktop(launch):
    renderer, copy, calls, behaviour = launch
    behaviour["hidden"] = behaviour["shown"] = "nothing"
    assert not renderer.run(copy, 60).outputs  # nothing either way: the syntax, not the desktop
    behaviour["hidden"] = "render"
    assert renderer.render(copy, 60).name.startswith("rendu-")
    assert fl_studio._hidden_renders is True


def test_what_fl_studio_asks_is_said_instead_of_waited_for(launch):
    renderer, copy, calls, behaviour = launch
    behaviour["hidden"] = "ask"
    with pytest.raises(RenderError, match="FL Studio attend une réponse : « FL Studio — Plugin introuvable : Serum »"):
        renderer.render(copy, 60)
    assert calls["shown"] == 0


def test_copies_rendered_together_never_show_fl_studio(launch, tmp_path, monkeypatch):
    # nothing rendered on its own desktop: the copies are left to ``render`` (alone, shown if need be), and the
    # folder render is not judged while FL has never rendered there
    renderer, _, calls, behaviour = launch
    monkeypatch.setattr(fl_studio.os, "cpu_count", lambda: 4)
    behaviour["hidden"] = "nothing"
    copies = []
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
        copies.append(tmp_path / name / f"{name}.flp")
        copies[-1].write_bytes(b"FLhd")
    told = []
    renderer.render_many(copies, 60, lambda copy, wav: told.append(copy))
    assert told == [] and calls == {"hidden": 1, "shown": 0}
    assert renderer.folders is None and all(c.read_bytes() == b"FLhd" for c in copies)
    monkeypatch.setattr(fl_studio, "_hidden_renders", True)  # FL renders there: now the same says it
    renderer.render_many(copies, 60, lambda copy, wav: told.append(copy))
    assert told == [] and calls["shown"] == 0 and renderer.folders is False


# -- the real desktop (Windows) -----------------------------------------------------------------------

def _script(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


DESKTOP_NAME = """
    import ctypes, sys
    from ctypes import wintypes as w
    user32, kernel32 = ctypes.WinDLL("user32"), ctypes.WinDLL("kernel32")
    user32.GetThreadDesktop.argtypes = [w.DWORD]
    user32.GetThreadDesktop.restype = w.HANDLE
    user32.GetUserObjectInformationW.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD,
                                                 ctypes.POINTER(w.DWORD)]
    desktop = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
    name, needed = ctypes.create_unicode_buffer(256), w.DWORD()
    user32.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), ctypes.byref(needed))
    open(sys.argv[1], "w", encoding="utf-8").write(name.value)
"""


@windows
def test_a_program_runs_on_a_desktop_that_is_not_the_users(tmp_path):
    out = tmp_path / "bureau.txt"
    script = _script(tmp_path, "bureau.py", DESKTOP_NAME)
    run = hidden_desktop.run_hidden([sys.executable, str(script), str(out)], tmp_path, 60, lambda: 0)
    assert run.returncode == 0 and not run.timed_out and run.dialog is None
    assert out.read_text(encoding="utf-8").startswith("Eden-")  # never the user's ("Default")


@windows
def test_two_programs_started_together_each_have_a_desktop_of_their_own(tmp_path):
    # two FL Studios side by side: each one's messages are read on its own desktop
    script = _script(tmp_path, "bureau.py", DESKTOP_NAME)
    outs = [tmp_path / f"bureau-{k}.txt" for k in range(2)]
    runs = [threading.Thread(target=hidden_desktop.run_hidden,
                             args=([sys.executable, str(script), str(out)], tmp_path, 60, lambda: 0)) for out in outs]
    for run in runs:
        run.start()
    for run in runs:
        run.join()
    names = {out.read_text(encoding="utf-8") for out in outs}
    assert len(names) == 2 and all(name.startswith("Eden-") for name in names)


@windows
def test_there_it_runs_at_a_low_priority(tmp_path):
    # what the user does on the PC goes first: the renders do not make it lag
    out = tmp_path / "priorite.txt"
    script = _script(tmp_path, "priorite.py", """
        import ctypes, sys
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.GetPriorityClass.argtypes = [ctypes.c_void_p]
        open(sys.argv[1], "w", encoding="utf-8").write(str(kernel32.GetPriorityClass(kernel32.GetCurrentProcess())))
    """)
    run = hidden_desktop.run_hidden([sys.executable, str(script), str(out)], tmp_path, 60, lambda: 0)
    assert run.returncode == 0
    assert int(out.read_text(encoding="utf-8")) == hidden_desktop.BELOW_NORMAL_PRIORITY_CLASS


@windows
def test_a_message_waiting_for_an_answer_is_read_and_the_program_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(hidden_desktop, "DIALOG_PATIENCE_S", 1.0)
    script = _script(tmp_path, "message.py", """
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, "Plugin introuvable : Serum", "FL Studio", 0)
    """)
    start = time.monotonic()
    run = hidden_desktop.run_hidden([sys.executable, str(script)], tmp_path, 60, lambda: 0)
    assert run.dialog is not None and "FL Studio" in run.dialog and "Plugin introuvable : Serum" in run.dialog
    assert not run.timed_out and time.monotonic() - start < 30


@windows
def test_a_program_that_never_ends_is_closed_at_the_timeout(tmp_path):
    script = _script(tmp_path, "attente.py", "import time\ntime.sleep(120)\n")
    start = time.monotonic()
    run = hidden_desktop.run_hidden([sys.executable, str(script)], tmp_path, 2, lambda: 0)
    assert run.timed_out and run.returncode is None and time.monotonic() - start < 20
