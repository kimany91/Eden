"""The user's FL Studio projects: every .flp of the folder where they save them.

The folder is chosen once and kept in the settings; the home page lists what it holds, newest
first. FL Studio's own backups (its "Backup" folder, "overwritten at" and autosave copies) and
templates are left out: they are not songs to mix. The search stays shallow and bounded, so that
a folder chosen too wide (a whole drive) does not keep Eden waiting.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

SKIPPED_FOLDERS = {"backup", "backups", "templates", "__macosx"}
BACKUP_NAME = re.compile(r"\((overwritten at [^)]*|autosave[^)]*)\)\s*$", re.I)
MAX_DEPTH = 4  # the folder itself is 0: Projects/Artist/Album/Song/song.flp is still found
MAX_FOLDERS = 4000
MAX_PROJECTS = 2000


@dataclass(frozen=True)
class ProjectEntry:
    path: Path
    folder: str  # subfolder from the projects folder, "" at its top
    modified: float  # seconds since the epoch

    @property
    def name(self) -> str:
        return self.path.stem


def default_projects_folder(home: Path | None = None) -> Path | None:
    """Where FL Studio saves projects unless told otherwise (Documents, or Documents on OneDrive)."""
    home = home or Path.home()
    for documents in (home / "Documents", home / "OneDrive" / "Documents"):
        folder = documents / "Image-Line" / "FL Studio" / "Projects"
        if folder.is_dir():
            return folder
    return None


def find_projects(folder: Path) -> list[ProjectEntry]:
    """The .flp files under ``folder`` (up to ``MAX_DEPTH`` folders down), most recently saved first."""
    found: list[ProjectEntry] = []
    pending = [(folder, 0)]
    visited = 0
    while pending and visited < MAX_FOLDERS and len(found) < MAX_PROJECTS:
        current, depth = pending.pop()
        visited += 1
        try:
            entries = list(os.scandir(current))
        except OSError:  # no access, or gone meanwhile
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if depth < MAX_DEPTH and not entry.name.startswith(".") \
                            and entry.name.lower() not in SKIPPED_FOLDERS:
                        pending.append((Path(entry.path), depth + 1))
                elif entry.name.lower().endswith(".flp") and not BACKUP_NAME.search(entry.name[:-4]):
                    path = Path(entry.path)
                    sub = path.parent.relative_to(folder)
                    found.append(ProjectEntry(path, "" if sub == Path(".") else sub.as_posix(),
                                              entry.stat().st_mtime))
            except OSError:
                continue
    return sorted(found, key=lambda e: e.modified, reverse=True)
