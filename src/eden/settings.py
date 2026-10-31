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
    projects_folder: str | None = None  # where the user saves FL projects; FL's own folder when empty
    # whether several FL Studios render at once on this PC, learned from the renders (None until tried)
    render_side_by_side: bool | None = None
    # the mastering window's choices (see eden.mix.master.MasterSettings)
    master_mode: str = "simple"  # "aucun" | "simple" | "complet"
    master_target_lufs: float = -9.0  # felt loudness aimed at 100 % intensity
    master_ceiling_dbtp: float | None = None  # None: chosen on the density (−2, or −3 when dense)
    master_bus_compression: bool = True  # complet only
    master_soft_clip: bool = True  # complet only
    master_budget_db: float = 6.0  # clip + limiter on the recurring peaks


def master_settings(settings: Settings):
    """The ``MasterSettings`` these stored choices describe (imported here: the master module
    loads scipy, which every ``eden`` command should not)."""
    from eden.mix.master import MASTER_MODES, MasterSettings

    mode = settings.master_mode if settings.master_mode in MASTER_MODES else "simple"
    return MasterSettings(mode=mode, target_lufs=float(settings.master_target_lufs),
                          ceiling_dbtp=settings.master_ceiling_dbtp,
                          bus_compression=bool(settings.master_bus_compression),
                          soft_clip=bool(settings.master_soft_clip),
                          budget_db=float(settings.master_budget_db))


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
