"""Protection of the user's FL Studio project.

Rules enforced here:
* the original .flp is only ever opened for reading;
* every inspection records the SHA-256 of the file and checks it again at
  the end, so a project saved by FL Studio during the analysis is detected;
* Eden's own files live in a separate workspace, never next to the project.

The original is never copied: Eden reads it, and the temporary copies FL
Studio renders from (see eden.render) are deleted as soon as FL is done.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path


class ProjectChangedError(RuntimeError):
    """The project file changed while Eden was reading it."""


@dataclass(frozen=True)
class FileFingerprint:
    path: str
    size: int
    mtime_ns: int
    sha256: str


def fingerprint_bytes(path: Path, data: bytes) -> FileFingerprint:
    st = path.stat()
    return FileFingerprint(str(path), len(data), st.st_mtime_ns, hashlib.sha256(data).hexdigest())


def read_project_bytes(path: Path) -> tuple[bytes, FileFingerprint]:
    """Read the whole project once, read-only, and fingerprint it."""
    with open(path, "rb") as fh:
        data = fh.read()
    return data, fingerprint_bytes(path, data)


def verify_unchanged(path: Path, before: FileFingerprint) -> None:
    with open(path, "rb") as fh:
        data = fh.read()
    if hashlib.sha256(data).hexdigest() != before.sha256:
        raise ProjectChangedError(
            "Le fichier du projet a été modifié pendant l'analyse "
            "(probablement enregistré depuis FL Studio). Relance l'analyse."
        )


def eden_home() -> Path:
    env = os.environ.get("EDEN_HOME")
    if env:
        return Path(env)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Eden"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "eden"


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")
    return s[:60] or "projet"


class Workspace:
    """Per-project folder holding Eden's reports, FL Studio renders and (later) mixes."""

    def __init__(self, project_path: Path, home: Path | None = None) -> None:
        project_path = project_path.resolve()
        key = hashlib.sha256(str(project_path).lower().encode("utf-8")).hexdigest()[:10]
        self.project_path = project_path
        self.root = (home or eden_home()) / "projects" / f"{_slug(project_path.stem)}-{key}"
        if self.root == project_path.parent or project_path.parent in self.root.parents:
            # Never write inside the user's project folder.
            raise RuntimeError("Le dossier de travail d'Eden ne peut pas être dans le dossier du projet")

    @property
    def inspections(self) -> Path:
        return self.root / "inspections"

    def new_inspection_path(self) -> Path:
        self.inspections.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        return self.inspections / f"{stamp}.json"
