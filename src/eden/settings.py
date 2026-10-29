"""User settings stored in Eden's workspace (settings.json)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from eden.safety import eden_home


@dataclass
class Settings:
    fl_path: str | None = None  # FL64.exe; detected automatically when empty
    # FL Studio command-line arguments for one render; {project} and {folder}
    # are replaced. None until `eden fl-probe` has found a working syntax.
    render_args: list[str] | None = None
    render_timeout_s: float = 900.0
    null_test_threshold_db: float = -60.0


def settings_path() -> Path:
    return eden_home() / "settings.json"


def load_settings(path: Path | None = None) -> Settings:
    path = path or settings_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    known = {k: v for k, v in raw.items() if k in Settings.__dataclass_fields__}
    try:
        return Settings(**known)
    except TypeError:
        return Settings()


def save_settings(settings: Settings, path: Path | None = None) -> None:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
