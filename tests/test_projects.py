"""The user's FL projects (project/library.py): the folder chosen once, every .flp it holds, newest
first, FL Studio's backups left out; and how the home page shows them."""

import os
import time
from datetime import datetime
from pathlib import Path

import pytest

from eden.gui import viewmodel
from eden.project import library
from eden.project.library import ProjectEntry, default_projects_folder, find_projects


def _flp(path: Path, hours_ago: float = 0.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"FLhd")
    when = time.time() - hours_ago * 3600
    os.utime(path, (when, when))
    return path


def test_every_project_of_the_folder_newest_first(tmp_path):
    _flp(tmp_path / "Freestyle.flp", 5)
    _flp(tmp_path / "Nuit blanche" / "Nuit blanche.flp", 1)
    _flp(tmp_path / "Album" / "Gang" / "Gang.flp", 30)
    (tmp_path / "Album" / "Gang" / "voix.wav").write_bytes(b"RIFF")  # not a project
    found = find_projects(tmp_path)
    assert [e.name for e in found] == ["Nuit blanche", "Freestyle", "Gang"]
    assert [e.folder for e in found] == ["Nuit blanche", "", "Album/Gang"]


def test_fl_studio_backups_templates_and_hidden_folders_are_left_out(tmp_path):
    _flp(tmp_path / "Mon son.flp")
    _flp(tmp_path / "Backup" / "Mon son (overwritten at 1534h27).flp")
    _flp(tmp_path / "Mon son (overwritten at 0912h03).flp")  # a backup saved next to it
    _flp(tmp_path / "Mon son (autosave).flp")
    _flp(tmp_path / "Templates" / "Rap.flp")
    _flp(tmp_path / ".cache" / "old.flp")
    assert [e.name for e in find_projects(tmp_path)] == ["Mon son"]


def test_a_folder_chosen_too_wide_is_searched_only_so_deep(tmp_path):
    deep = tmp_path.joinpath(*[f"d{i}" for i in range(library.MAX_DEPTH + 1)])
    _flp(deep / "trop loin.flp")
    _flp(deep.parent / "assez près.flp")
    assert [e.name for e in find_projects(tmp_path)] == ["assez près"]


def test_a_missing_folder_has_no_projects(tmp_path):
    assert find_projects(tmp_path / "débranché") == []


def test_fl_studios_own_projects_folder_is_the_default(tmp_path):
    assert default_projects_folder(tmp_path) is None
    onedrive = tmp_path / "OneDrive" / "Documents" / "Image-Line" / "FL Studio" / "Projects"
    onedrive.mkdir(parents=True)
    assert default_projects_folder(tmp_path) == onedrive
    documents = tmp_path / "Documents" / "Image-Line" / "FL Studio" / "Projects"
    documents.mkdir(parents=True)
    assert default_projects_folder(tmp_path) == documents


def test_the_home_page_says_when_each_project_was_saved():
    now = datetime(2026, 10, 30, 15, 0).timestamp()
    at = lambda *d: datetime(*d).timestamp()  # noqa: E731
    assert viewmodel.saved_when(at(2026, 10, 30, 9, 5), now) == "Aujourd'hui à 09:05"
    assert viewmodel.saved_when(at(2026, 10, 29, 23, 59), now) == "Hier à 23:59"
    assert viewmodel.saved_when(at(2026, 10, 26, 12, 0), now) == "Il y a 4 jours"
    assert viewmodel.saved_when(at(2026, 9, 2, 12, 0), now) == "02/09/2026"
    rows = viewmodel.project_rows([ProjectEntry(Path("/p/Album/Gang/Gang.flp"), "Album/Gang", now),
                                   ProjectEntry(Path("/p/Nuit/Nuit.flp"), "Nuit", now),
                                   ProjectEntry(Path("/p/Démos/hook.flp"), "Démos", now)], now)
    # FL gives each project a folder of its name: only what says more is shown
    assert [r["folder"] for r in rows] == ["Album", "", "Démos"]
    assert rows[0] == {"name": "Gang", "path": str(Path("/p/Album/Gang/Gang.flp")), "folder": "Album",
                       "saved": "Aujourd'hui à 15:00"}


# -- the controller: the folder kept for the next times ------------------------------------------

@pytest.fixture
def controller(monkeypatch):
    pytest.importorskip("PySide6.QtCore")
    monkeypatch.setattr(library, "default_projects_folder", lambda home=None: None)
    from eden.gui.controller import EdenController

    return lambda: EdenController(check_updates=False)


def test_the_folder_is_chosen_once_and_kept(controller, tmp_path):
    from eden.settings import load_settings

    c = controller()
    assert c.projectsFolder == "" and c.projects == [] and c.projectsMessage == ""  # the page asks for it
    _flp(tmp_path / "Projects" / "Mon son" / "Mon son.flp")
    c.setProjectsFolder((tmp_path / "Projects").as_uri())
    assert load_settings().projects_folder == str(tmp_path / "Projects")
    assert [p["name"] for p in c.projects] == ["Mon son"] and c.projectsMessage == ""
    again = controller()  # the next time Eden opens
    assert again.projectsFolder == str(tmp_path / "Projects") and len(again.projects) == 1


def test_the_list_follows_what_is_saved_and_says_why_it_is_empty(controller, tmp_path):
    c = controller()
    c.setProjectsFolder(str(tmp_path))
    assert c.projects == [] and "Aucun projet" in c.projectsMessage
    _flp(tmp_path / "Nouveau.flp")
    c.refreshProjects()
    assert [p["name"] for p in c.projects] == ["Nouveau"] and c.projectsMessage == ""
    c.setProjectsFolder(str(tmp_path / "débranché"))
    assert c.projects == [] and "introuvable" in c.projectsMessage


def test_fl_studios_folder_is_shown_until_another_is_chosen(monkeypatch, tmp_path):
    pytest.importorskip("PySide6.QtCore")
    fl_folder = tmp_path / "Image-Line" / "FL Studio" / "Projects"
    _flp(fl_folder / "Démo.flp")
    monkeypatch.setattr(library, "default_projects_folder", lambda home=None: fl_folder)
    from eden.gui.controller import EdenController
    from eden.settings import load_settings

    c = EdenController(check_updates=False)
    assert c.projectsFolder == str(fl_folder) and [p["name"] for p in c.projects] == ["Démo"]
    assert load_settings().projects_folder is None  # nothing written until the user chooses
