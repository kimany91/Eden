"""Locate the audio files referenced by a project.

FL Studio stores sample paths either as absolute paths or with placeholders
such as ``%FLStudioFactoryData%`` and ``%FLStudioUserData%``. Files may also
have been moved together with the project folder. This module never copies
or modifies audio files; it only looks for them and reads their headers.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath

_PLACEHOLDER = re.compile(r"%([A-Za-z]+)%")

AUDIO_EXTENSIONS = {".wav", ".aif", ".aiff", ".flac", ".ogg", ".mp3", ".wv"}


@dataclass
class SearchRoots:
    """Folders used to expand FL Studio path placeholders."""

    factory_data: list[Path] = field(default_factory=list)
    user_data: list[Path] = field(default_factory=list)
    extra_dirs: list[Path] = field(default_factory=list)

    @classmethod
    def default(cls) -> "SearchRoots":
        factory: list[Path] = []
        user: list[Path] = []
        program_files = os.environ.get("ProgramFiles")
        if program_files:
            il = Path(program_files) / "Image-Line"
            if il.is_dir():
                factory.extend(sorted(il.glob("FL Studio*"), reverse=True))
        docs = Path.home() / "Documents" / "Image-Line" / "FL Studio"
        if docs.is_dir():
            user.append(docs)
        return cls(factory_data=factory, user_data=user)


@dataclass
class AudioInfo:
    sample_rate: int
    channels: int
    frames: int
    duration_s: float
    format: str
    subtype: str


@dataclass
class SourceFile:
    stored_path: str
    resolved_path: str | None = None
    status: str = "missing"  # found | found_elsewhere | missing | unreadable
    is_factory: bool = False
    audio: AudioInfo | None = None
    size_bytes: int | None = None
    note: str | None = None


def _to_local(stored: str) -> Path:
    """Convert a Windows-style stored path to a local Path."""
    if os.name == "nt":
        return Path(stored)
    return Path(*PureWindowsPath(stored).parts) if "\\" in stored else Path(stored)


def _expand(stored: str, roots: SearchRoots) -> list[Path]:
    m = _PLACEHOLDER.match(stored)
    if not m:
        return [_to_local(stored)]
    key = m.group(1).lower()
    rest = stored[m.end():].lstrip("\\/")
    bases = {
        "flstudiofactorydata": roots.factory_data,
        "flstudiouserdata": roots.user_data,
    }.get(key, [])
    return [base / _to_local(rest) for base in bases]


def _basename(stored: str) -> str:
    return PureWindowsPath(stored).name if "\\" in stored else Path(stored).name


class FileIndex:
    """Lazy, bounded index of file names below some folders (case-insensitive)."""

    def __init__(self, dirs: list[Path], max_files: int = 50000) -> None:
        self.dirs = dirs
        self.max_files = max_files
        self._index: dict[str, Path] | None = None
        self.truncated = False

    def find(self, name: str) -> Path | None:
        if self._index is None:
            self._index = {}
            count = 0
            for d in self.dirs:
                if not d.is_dir():
                    continue
                for root, _dirs, files in os.walk(d):
                    for f in files:
                        self._index.setdefault(f.lower(), Path(root) / f)
                        count += 1
                    if count > self.max_files:
                        self.truncated = True
                        break
        return self._index.get(name.lower())


def read_audio_info(path: Path) -> AudioInfo | None:
    try:
        import soundfile as sf
    except ImportError:  # pragma: no cover - dependency is declared
        return None
    try:
        info = sf.info(str(path))
    except Exception:
        return None
    return AudioInfo(
        sample_rate=int(info.samplerate),
        channels=int(info.channels),
        frames=int(info.frames),
        duration_s=float(info.duration),
        format=str(info.format),
        subtype=str(info.subtype),
    )


def resolve_source(
    stored: str, project_dir: Path, roots: SearchRoots, index: FileIndex | None = None
) -> SourceFile:
    src = SourceFile(stored_path=stored)
    src.is_factory = stored.lower().startswith("%flstudiofactorydata%")

    found: Path | None = None
    for candidate in _expand(stored, roots):
        if candidate.is_file():
            found = candidate
            src.status = "found"
            break

    if found is None:
        # Moved projects: look for the same file name next to the project.
        index = index or FileIndex([project_dir, *roots.extra_dirs])
        found = index.find(_basename(stored))
        if found is not None:
            src.status = "found_elsewhere"
            src.note = "Fichier retrouvé par son nom, à un autre emplacement que celui du projet"

    if found is None:
        if src.is_factory:
            src.note = "Échantillon fourni avec FL Studio (dossier d'installation non accessible ici)"
        return src

    src.resolved_path = str(found)
    try:
        src.size_bytes = found.stat().st_size
    except OSError:
        pass
    if found.suffix.lower() in AUDIO_EXTENSIONS:
        src.audio = read_audio_info(found)
        if src.audio is None:
            src.status = "unreadable"
            src.note = "Fichier présent mais illisible par le décodeur audio"
    return src
