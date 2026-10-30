"""From FL Studio's renders to the final, mastered song.

    parts (voices, groups, rest) → Eden's mix → Eden's master → checks
    → saved as a version (final WAV + every decision and its reason)

Versions are kept in Eden's workspace so earlier mixes can be compared,
restored or exported again. The project's own Master effects are not used:
the final sound is Eden's (the user chose Eden for the mastering).
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import soundfile as sf

from eden.mix import ProgressCallback
from eden.mix.engine import MixOutcome, PartResult, SongAnalysis, mix
from eden.mix.loudness import integrated_loudness, sample_peak_db, true_peak_db
from eden.mix.master import MasterChecks, master
from eden.mix.parts import Parts, PartsError, split
from eden.mix.treatments import Treatment
from eden.project.inspector import InspectionReport
from eden.project.model import to_jsonable
from eden.render.pipeline import RenderResult
from eden.safety import Workspace, read_project_bytes

StepCallback = Callable[[int, int, str], None]

STEPS = (
    "Préparation des pistes rendues par FL Studio",
    "Mixage : voix, espace, stéréo, basses",
    "Mastering Eden",
    "Vérification du résultat final",
)


class MixError(RuntimeError):
    pass


@dataclass
class AudioStats:
    loudness_lufs: float
    true_peak_db: float
    sample_peak_db: float
    duration_s: float
    sample_rate: int
    subtype: str


@dataclass
class MixVersion:
    id: str
    created_at: str
    intensity: float
    final_wav: str
    parts: list[PartResult]
    song: SongAnalysis
    master: list[Treatment]
    checks: MasterChecks
    staging_gain_db: float
    original: AudioStats
    final: AudioStats
    warnings: list[str] = field(default_factory=list)
    original_wav: str = ""  # the song as FL renders it, for the before / after comparison

    def to_json(self) -> str:
        return json.dumps(to_jsonable(self), ensure_ascii=False, indent=2)


def stats(path: Path) -> AudioStats:
    data, sr = sf.read(str(path), dtype="float64", always_2d=True)
    return AudioStats(integrated_loudness(data, sr), true_peak_db(data, sr), sample_peak_db(data),
                      data.shape[0] / sr, sr, str(sf.info(str(path)).subtype))


def fl_space_status(report: InspectionReport, parts: Parts) -> dict[str, str]:
    """Per voice: none (no FL reverb/delay), tracked (rendered apart) or untracked.

    The reverbs and delays are the source's ``space_effects``: an unidentified plugin on an
    insert named like an effect return counts, so Eden adds no space of its own on top of it.
    """
    sources = {f"ch{s.channel}": s for s in report.sources}
    status = {}
    for v in parts.voices:
        s = sources.get(v.key)
        has_space = bool(s and s.space_effects)
        status[v.key] = "tracked" if v.dry is not None else ("untracked" if has_space else "none")
    return status


def mix_project(
    project: Path,
    report: InspectionReport,
    renders: RenderResult,
    intensity: float = 1.0,
    workspace_home: Path | None = None,
    on_step: StepCallback | None = None,
    on_progress: ProgressCallback | None = None,
) -> MixVersion:
    """``on_step`` is told each of STEPS; ``on_progress``, during the mix and the master, what Eden
    is doing and the share of that step done (None: a detail of the running step)."""
    def step(i: int) -> None:
        if on_step:
            on_step(i, len(STEPS), STEPS[i])

    if not renders.ok:
        raise MixError("Le son récupéré depuis FL Studio n'a pas passé ses vérifications : relance "
                       "la récupération du son (bouton « Récupérer le son depuis FL Studio », "
                       "ou eden render)")
    _, fp = read_project_bytes(project)
    if fp.sha256 != report.file.sha256 or fp.sha256 != renders.project_sha256:
        raise MixError("Le projet a changé depuis la récupération du son : relance l'analyse")

    step(0)
    try:
        parts = split(report, renders)
    except PartsError as exc:
        raise MixError(str(exc)) from exc
    if not parts.voices:
        raise MixError("Aucune voix n'a été rendue séparément : rien à mixer")

    step(1)
    outcome: MixOutcome = mix(parts, intensity, report.project.tempo_bpm, fl_space_status(report, parts),
                              progress=on_progress)

    step(2)
    mastered = master(outcome.premaster, parts.sample_rate, intensity, report.project.tempo_bpm,
                      progress=on_progress)

    step(3)
    stamp = datetime.now(UTC)
    mixes = Workspace(project, workspace_home).root / "mixes"
    version_id = stamp.strftime("%Y%m%d-%H%M%S")
    suffix = 1
    while (mixes / version_id).exists():
        suffix += 1
        version_id = f"{stamp:%Y%m%d-%H%M%S}-{suffix}"
    folder = mixes / version_id
    folder.mkdir(parents=True)
    final = folder / "final.wav"
    sf.write(str(final), mastered.audio, parts.sample_rate, subtype="FLOAT")

    original_wav = renders.wav("original")
    original_stats = stats(original_wav)
    final_stats = stats(final)
    warnings = [*renders.warnings, *parts.warnings, *outcome.warnings, *mastered.warnings]
    if intensity > 0 and math.isfinite(original_stats.loudness_lufs) and \
            final_stats.loudness_lufs < original_stats.loudness_lufs - 1.0:
        warnings.append(f"Le master Eden ({final_stats.loudness_lufs:.1f} LUFS) est moins fort que ton "
                        f"export FL Studio ({original_stats.loudness_lufs:.1f} LUFS)")
    version = MixVersion(version_id, stamp.isoformat(timespec="seconds"), outcome.intensity, str(final),
                         outcome.parts, outcome.song, mastered.treatments, mastered.checks,
                         outcome.staging_gain_db, original_stats, final_stats, warnings, str(original_wav))
    (folder / "version.json").write_text(version.to_json(), encoding="utf-8")
    return version


def list_versions(project: Path, workspace_home: Path | None = None) -> list[dict]:
    """Saved mixes of a project, newest first (as stored, for display and export)."""
    root = Workspace(project, workspace_home).root / "mixes"
    versions = []
    for meta in sorted(root.glob("*/version.json"), reverse=True):
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if Path(data.get("final_wav", "")).is_file():
            versions.append(data)
    return versions
