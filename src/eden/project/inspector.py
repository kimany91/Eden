"""Read-only inspection of an FL Studio project.

Pipeline (each step reports real progress through ``on_step``):
    1. read the .flp once, read-only, and fingerprint it
    2. parse the event stream
    3. locate referenced audio files and read their headers
    4. follow the mixer routing of each source and list existing effects
    5. guess the role of each source
    6. verify the project file was not modified meanwhile
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from collections.abc import Callable

from eden import __version__
from eden.flp.events import FlpFormatError
from eden.flp.parser import parse_bytes
from eden.project.classify import RoleGuess, guess_role
from eden.project.model import MASTER_INSERT, FlpProject, to_jsonable
from eden.project.plugins import categorize
from eden.project.sources import FileIndex, SearchRoots, SourceFile, resolve_source
from eden.safety import FileFingerprint, Workspace, read_project_bytes, verify_unchanged

STEPS = (
    "Lecture du fichier",
    "Décodage du projet",
    "Recherche des fichiers audio",
    "Analyse du routage et des effets",
    "Identification des pistes",
    "Vérification de l'intégrité du projet",
)

StepCallback = Callable[[int, int, str], None]

# Generators that do not produce audio themselves.
NON_AUDIO_GENERATORS = {"MIDI Out", "Fruity Keyboard Controller"}

# Effects that put a voice in a space: FL renders the voices without them.
SPACE_CATEGORIES = {"reverb", "delay"}
# Insert names of an effect return ("Reverb", "Verb", "Delay vox", "Écho", "Space"…).
SPACE_INSERT_NAME = re.compile(r"verb|delay|[eé]cho|space", re.IGNORECASE)


class InspectionError(RuntimeError):
    def __init__(self, step: str, message: str) -> None:
        super().__init__(f"{step} : {message}")
        self.step = step
        self.message = message


@dataclass
class ExistingEffect:
    insert: int
    insert_label: str
    slot: int
    plugin: str
    category: str
    active: bool  # heard: slot on, dry/wet not at 0, insert and its effects on, insert reaching the Master
    # Why it is not heard (None when active): "off" (its slot or its insert's effects switched off),
    # "mix_zero" (dry/wet at 0), "insert_muted", "no_output" (the insert's output never reaches the Master).
    inactive_reason: str | None


@dataclass
class SourceAnalysis:
    channel: int
    label: str
    kind: str  # sampler (audio) | instrument (generator plugin)
    insert: int | None
    insert_label: str | None
    signal_path: list[int]  # inserts crossed until the Master
    reaches_master: bool
    existing_effects: list[ExistingEffect]
    role: RoleGuess
    clip_count: int
    first_seconds: float | None
    last_seconds: float | None
    sample: SourceFile | None = None
    plugin: str | None = None

    @property
    def space_effects(self) -> list[ExistingEffect]:
        """Its active reverbs and delays. An unidentified plugin counts too when it sits on an
        insert other than the source's own whose name says reverb, delay, echo or space: the
        user named that insert after the effect it holds."""
        return [e for e in self.existing_effects if e.active and (
            e.category in SPACE_CATEGORIES
            or (e.category == "unknown" and e.insert != self.insert
                and SPACE_INSERT_NAME.search(e.insert_label) is not None))]


@dataclass
class InspectionReport:
    eden_version: str
    inspected_at: str
    file: FileFingerprint
    project: FlpProject
    sources: list[SourceAnalysis]
    master_effects: list[ExistingEffect]
    used_inserts: list[int]
    project_end_seconds: float | None
    limitations: list[str]
    warnings: list[str] = field(default_factory=list)
    report_path: str | None = None

    def to_json(self) -> str:
        return json.dumps(to_jsonable(self), ensure_ascii=False, indent=2)

    @property
    def vocal_sources(self) -> list[SourceAnalysis]:
        return [s for s in self.sources if s.role.is_vocal]


LIMITATIONS = [
    "Les paramètres internes des plugins (VST/VST3 et la plupart des plugins FL) sont stockés "
    "sous forme de blocs opaques : Eden identifie le plugin, son emplacement et son état "
    "activé/désactivé, pas ses réglages. Ces réglages ne sont lisibles qu'à l'intérieur de "
    "FL Studio ; le son qu'ils produisent, lui, est récupéré par le rendu FL Studio.",
    "Les cibles des clips d'automation ne sont pas encore décodées : Eden détecte les clips "
    "d'automation et leur position, pas le paramètre qu'ils pilotent.",
    "Les durées en secondes supposent un tempo constant ; une automation de tempo n'est pas "
    "prise en compte.",
    "Le son réel du projet (effets, instruments virtuels, automations) n'est pas dans le .flp : "
    "Eden le fait produire par FL Studio (« Récupérer le son depuis FL Studio »).",
    "Le format .flp n'est pas documenté par Image-Line ; il a été vérifié sur FL Studio 20.8. "
    "Les versions plus récentes peuvent contenir des informations non décodées (voir les "
    "avertissements).",
]


def _signal_path(project: FlpProject, start: int) -> tuple[list[int], bool]:
    """Breadth-first walk of audible routes from ``start``; returns (inserts, reaches_master)."""
    seen: list[int] = []
    queue = [start]
    reaches = False
    while queue:
        idx = queue.pop(0)
        if idx in seen:
            continue
        seen.append(idx)
        if idx == MASTER_INSERT:
            reaches = True
            continue
        ins = project.insert(idx)
        if ins is None or ins.enabled is False:
            continue
        queue.extend(r.target for r in ins.routes if r.audible and r.target not in seen)
    return seen, reaches


def _effects_on(project: FlpProject, inserts: list[int]) -> list[ExistingEffect]:
    """The effects of ``inserts``. One is active only when FL plays it: its slot is on with its
    dry/wet not at 0 (when stored), its insert and the insert's effects are on, and the insert's
    output reaches the Master (a muted return, or one routed nowhere, is not heard). Otherwise
    ``inactive_reason`` says why, the first that applies of: switched off (its slot or its
    insert's effects), dry/wet at 0, insert muted, insert output that never reaches the Master."""
    out = []
    for idx in inserts:
        ins = project.insert(idx)
        if ins is None:
            continue
        if ins.enabled is False:
            insert_reason = "insert_muted"
        elif idx != MASTER_INSERT and not _signal_path(project, idx)[1]:
            insert_reason = "no_output"
        else:
            insert_reason = None
        for slot in ins.slots:
            category = categorize(slot.plugin)
            slot.plugin.category = category
            if slot.enabled is False or ins.effects_enabled is False:
                reason = "off"
            elif slot.mix_raw == 0:
                reason = "mix_zero"
            else:
                reason = insert_reason
            out.append(ExistingEffect(idx, ins.label, slot.index, slot.plugin.label, category,
                                      reason is None, reason))
    return out


def inspect_project(
    path: str | Path,
    roots: SearchRoots | None = None,
    workspace_home: Path | None = None,
    archive_report: bool = True,
    on_step: StepCallback | None = None,
) -> InspectionReport:
    path = Path(path)
    roots = roots or SearchRoots.default()
    total = len(STEPS)

    def step(i: int) -> str:
        if on_step:
            on_step(i, total, STEPS[i])
        return STEPS[i]

    name = step(0)
    if path.suffix.lower() != ".flp":
        raise InspectionError(name, f"« {path.name} » n'est pas un fichier .flp")
    try:
        data, fp = read_project_bytes(path)
    except FileNotFoundError:
        raise InspectionError(name, f"fichier introuvable : {path}") from None
    except OSError as exc:
        raise InspectionError(name, f"lecture impossible ({exc})") from exc

    name = step(1)
    try:
        project = parse_bytes(data)
    except FlpFormatError as exc:
        raise InspectionError(name, str(exc)) from exc

    warnings = list(project.warnings)
    if project.fl_version is None:
        warnings.append("Version de FL Studio introuvable dans le projet")

    # Playlist usage of each channel (current arrangement = first one with clips)
    clips_by_channel: dict[int, list] = {}
    pattern_channels = {pat.index: pat.channels for pat in project.patterns}
    for arr in project.arrangements:
        for clip in arr.clips:
            if clip.source == "channel":
                clips_by_channel.setdefault(clip.source_index, []).append(clip)
            else:
                for ch_idx in pattern_channels.get(clip.source_index, []):
                    clips_by_channel.setdefault(ch_idx, []).append(clip)
    end_ticks = max(
        (c.position_ticks + c.length_ticks for a in project.arrangements for c in a.clips), default=0
    )
    project_end = project.ticks_to_seconds(end_ticks) if end_ticks else None

    name = step(2)
    project_dir = path.resolve().parent
    samples: dict[int, SourceFile] = {}
    index = FileIndex([project_dir, *roots.extra_dirs])
    for ch in project.channels:
        if ch.kind == "sampler" and ch.sample_path:
            samples[ch.index] = resolve_source(ch.sample_path, project_dir, roots, index)
    if index.truncated:
        warnings.append("Dossier du projet très volumineux : recherche des fichiers déplacés incomplète")

    name = step(3)
    sources: list[SourceAnalysis] = []
    used_inserts: set[int] = set()
    track_names = {
        (a.index, t.number): t.name for a in project.arrangements for t in a.tracks if t.name
    }
    analyses_input = []
    for ch in project.channels:
        if ch.kind not in ("sampler", "instrument"):
            continue
        if ch.plugin is not None and ch.plugin.internal_name in NON_AUDIO_GENERATORS:
            continue
        if ch.kind == "sampler" and not ch.sample_path and ch.index not in clips_by_channel:
            continue  # empty sampler channel: nothing to mix
        insert_idx = ch.insert if ch.insert is not None else MASTER_INSERT
        path_inserts, reaches = _signal_path(project, insert_idx)
        used_inserts.update(path_inserts)
        analyses_input.append((ch, insert_idx, path_inserts, reaches))
        if not reaches:
            warnings.append(f"« {ch.label} » n'atteint pas le Master (routage coupé ou insert désactivé)")

    name = step(4)
    for ch, insert_idx, path_inserts, reaches in analyses_input:
        ins = project.insert(insert_idx)
        clips = clips_by_channel.get(ch.index, [])
        sample = samples.get(ch.index)
        names = [("Canal", ch.name or "")]
        if ins is not None and ins.name and insert_idx != MASTER_INSERT:
            names.append(("Insert", ins.name))
        for tname in sorted({track_names.get((c.arrangement, c.track)) for c in clips} - {None}):
            names.append(("Piste de playlist", tname))
        if sample is not None:
            names.append(("Fichier", Path(sample.stored_path.replace("\\", "/")).stem))
        role = guess_role(
            names,
            sample_path=ch.sample_path,
            channels=sample.audio.channels if sample and sample.audio else None,
            duration_s=sample.audio.duration_s if sample and sample.audio else None,
            project_duration_s=project_end,
        )
        if ch.kind == "instrument" and role.role == "unknown":
            role.role = "music"
            role.reasons.append("Instrument virtuel (générateur) sans autre indice")
        sources.append(SourceAnalysis(
            channel=ch.index,
            label=ch.label,
            kind=ch.kind,
            insert=insert_idx,
            insert_label=ins.label if ins else None,
            signal_path=path_inserts,
            reaches_master=reaches,
            existing_effects=_effects_on(project, [i for i in path_inserts if i != MASTER_INSERT]),
            role=role,
            clip_count=len(clips),
            first_seconds=min((c.start_seconds for c in clips if c.start_seconds is not None), default=None),
            last_seconds=max(
                ((c.start_seconds or 0) + (c.length_seconds or 0) for c in clips), default=None
            ),
            sample=sample,
            plugin=ch.plugin.label if ch.plugin else None,
        ))
    master_effects = _effects_on(project, [MASTER_INSERT])

    for ins in project.inserts:  # categorize remaining slots for the report
        for slot in ins.slots:
            slot.plugin.category = categorize(slot.plugin)

    if not any(s.role.is_vocal for s in sources):
        warnings.append(
            "Aucune piste n'a été reconnue comme voix : vérifiez les noms des pistes ou "
            "indiquez manuellement les voix."
        )
    missing = [s for s in sources if s.sample and s.sample.status == "missing" and not s.sample.is_factory]
    for s in missing:
        warnings.append(f"Fichier audio introuvable pour « {s.label} » : {s.sample.stored_path}")

    name = step(5)
    try:
        verify_unchanged(path, fp)
    except Exception as exc:
        raise InspectionError(name, str(exc)) from exc

    report = InspectionReport(
        eden_version=__version__,
        inspected_at=datetime.now(UTC).isoformat(timespec="seconds"),
        file=fp,
        project=project,
        sources=sources,
        master_effects=master_effects,
        used_inserts=sorted(used_inserts),
        project_end_seconds=project_end,
        limitations=list(LIMITATIONS),
        warnings=warnings,
    )
    if archive_report:
        report_path = Workspace(path, workspace_home).new_inspection_path()
        report.report_path = str(report_path)
        report_path.write_text(report.to_json(), encoding="utf-8")
    return report
