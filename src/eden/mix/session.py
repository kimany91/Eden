"""From FL Studio's renders to the final, mastered song.

    parts (voices + rest) → Eden's mix (pre-master, same level as before)
    → FL Studio plays it through the project's own Master → final checks
    → saved as a version (final WAV + every decision and its reason)

Versions are kept in Eden's workspace so earlier mixes can be compared,
restored or exported again.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import soundfile as sf

from eden.mix.engine import Part, PartResult, mix
from eden.mix.loudness import integrated_loudness, sample_peak_db, true_peak_db
from eden.project.inspector import InspectionReport
from eden.project.model import to_jsonable
from eden.render.fl_studio import RenderError, Renderer
from eden.render.master import master_pass
from eden.render.pipeline import RenderResult, sample_repairs
from eden.safety import Workspace, read_project_bytes

StepCallback = Callable[[int, int, str], None]

STEPS = (
    "Préparation des pistes rendues par FL Studio",
    "Analyse et mixage des voix",
    "Passage dans ton Master FL Studio",
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
    staging_gain_db: float
    original: AudioStats
    final: AudioStats
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(to_jsonable(self), ensure_ascii=False, indent=2)


def stats(path: Path) -> AudioStats:
    data, sr = sf.read(str(path), dtype="float64", always_2d=True)
    return AudioStats(integrated_loudness(data, sr), true_peak_db(data), sample_peak_db(data),
                      data.shape[0] / sr, sr, str(sf.info(str(path)).subtype))


def _load(path: Path) -> tuple[np.ndarray, int]:
    data, sr = sf.read(str(path), dtype="float64", always_2d=True)
    return data, sr


def _pad(x: np.ndarray, length: int, channels: int) -> np.ndarray:
    if x.shape[1] != channels:
        x = np.repeat(x[:, :1], channels, axis=1)
    return np.pad(x, ((0, length - x.shape[0]), (0, 0)))


def build_parts(report: InspectionReport, renders: RenderResult) -> tuple[list[Part], Part, int, float]:
    """Voices rendered alone by FL + the rest (pre-master minus the voices)."""
    premaster_path = renders.wav("premaster")
    if premaster_path is None:
        raise MixError("Le rendu de référence (pré-Master) est absent : relancez la récupération du son")
    premaster, fs = _load(premaster_path)
    labels = {s.channel: s for s in report.sources}
    voices_raw = []
    for job in renders.jobs:
        if job.job.kind != "vocal" or not job.wav_path:
            continue
        audio, sr = _load(Path(job.wav_path))
        if sr != fs:
            raise MixError(f"« {job.job.description} » n'a pas la même fréquence d'échantillonnage")
        source = labels.get(job.job.channels[0])
        voices_raw.append((job.job.channels[0], source, audio))
    length = max([premaster.shape[0], *(a.shape[0] for _, _, a in voices_raw)])
    channels = premaster.shape[1]
    premaster = _pad(premaster, length, channels)
    voices = [Part(f"ch{ch}", s.label if s else f"Canal {ch}", s.role.role if s else "vocal",
                   _pad(a, length, channels)) for ch, s, a in voices_raw]
    rest = premaster - sum((v.audio for v in voices), np.zeros_like(premaster))
    return voices, Part("rest", "Instru et reste du morceau", "rest", rest), fs, \
        integrated_loudness(premaster, fs)


def mix_project(
    project: Path,
    report: InspectionReport,
    renders: RenderResult,
    renderer: Renderer,
    intensity: float = 1.0,
    timeout_s: float = 900.0,
    workspace_home: Path | None = None,
    on_step: StepCallback | None = None,
) -> MixVersion:
    def step(i: int) -> None:
        if on_step:
            on_step(i, len(STEPS), STEPS[i])

    if not renders.ok:
        raise MixError("Le son récupéré depuis FL Studio n'a pas passé ses vérifications : "
                       "relancez « Récupérer le son depuis FL Studio »")
    original, fp = read_project_bytes(project)
    if fp.sha256 != report.file.sha256 or fp.sha256 != renders.project_sha256:
        raise MixError("Le projet a changé depuis la récupération du son : relancez l'analyse")

    step(0)
    voices, rest, fs, premaster_lufs = build_parts(report, renders)
    if not voices:
        raise MixError("Aucune voix n'a été rendue séparément : rien à mixer")

    step(1)
    outcome = mix(voices, rest, fs, intensity, premaster_lufs)

    step(2)
    stamp = datetime.now(UTC)
    mixes = Workspace(project, workspace_home).root / "mixes"
    version_id = stamp.strftime("%Y%m%d-%H%M%S")
    suffix = 1
    while (mixes / version_id).exists():
        suffix += 1
        version_id = f"{stamp:%Y%m%d-%H%M%S}-{suffix}"
    folder = mixes / version_id
    folder.mkdir(parents=True)
    mix_wav = folder / "mix-avant-master.wav"
    sf.write(str(mix_wav), outcome.premaster, fs, subtype="FLOAT")
    try:
        final = master_pass(original, report, sample_repairs(report), mix_wav, renders.calibration,
                            folder, renderer, timeout_s, name="final")
    except RenderError as exc:
        raise MixError(f"Le passage dans ton Master FL Studio a échoué : {exc}") from exc
    finally:
        mix_wav.unlink(missing_ok=True)

    step(3)
    original_stats = stats(renders.wav("original"))
    final_stats = stats(final)
    warnings = []
    if final_stats.true_peak_db > 0.0:
        warnings.append(f"Crête réelle à {final_stats.true_peak_db:+.1f} dBTP en sortie de ton Master : "
                        "risque de saturation à la lecture ou à la conversion en MP3")
    if math.isfinite(original_stats.loudness_lufs) and \
            abs(final_stats.loudness_lufs - original_stats.loudness_lufs) > 1.0:
        warnings.append(f"Volume final {final_stats.loudness_lufs:.1f} LUFS contre "
                        f"{original_stats.loudness_lufs:.1f} LUFS pour ton morceau d'origine")
    version = MixVersion(version_id, stamp.isoformat(timespec="seconds"), outcome.intensity,
                         str(final), outcome.parts, outcome.staging_gain_db, original_stats,
                         final_stats, warnings)
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
