"""Get the real sound of a project out of FL Studio, automatically.

    inspection → render plan → temporary copy → FL Studio render → copy deleted
    → checks → null test (sum of stems == pre-master mix)

FL Studio does all the sound: Eden only mutes parts of the project in a
temporary copy so that FL renders each part separately, with every effect
the user set (delays, Auto-Tune, echoes...). The copies go to FL together
(``Renderer.render_many``: several FL Studios at once where the PC has room),
and any left without audio is rendered alone. The copies are deleted once FL has
rendered them; only the audio stays, in Eden's workspace. The original
project and its folder are never modified. A manifest (with the hash of each
copy) is updated after every render so an interrupted run resumes where it
stopped.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Callable
from typing import NoReturn

import numpy as np
import soundfile as sf

from eden.flp.edit import FlpEditor
from eden.project.inspector import InspectionReport, inspect_project
from eden.project.model import MASTER_INSERT
from eden.render.fl_studio import RenderError, Renderer
from eden.render.plan import RenderJob, RenderPlan, plan_renders
from eden.render.verify import AudioCheck, NullTest, check_audio, load, null_test
from eden.safety import Workspace, read_project_bytes, verify_unchanged

# (the part whose audio is there, in any order, -1 when FL Studio starts and the part count for the final
# check; the number of steps; what is happening)
StepCallback = Callable[[int, int, str], None]
END_TOLERANCE_S = 0.1


@dataclass
class JobResult:
    job: RenderJob
    copy_sha256: str  # identifies the rendered content, to resume interrupted runs
    wav_path: str | None = None
    check: AudioCheck | None = None
    status: str = "pending"  # pending | done | resumed | failed
    error: str | None = None


@dataclass
class RenderResult:
    project: str
    project_sha256: str
    folder: str
    plan: RenderPlan
    jobs: list[JobResult]
    null_test: NullTest | None
    repairs: list[str]
    warnings: list[str] = field(default_factory=list)
    # the mix before the Master rebuilt from its parts, when FL's render of it clipped (an integer WAV) while
    # the parts sum to it everywhere else
    premaster_sum: str | None = None

    @property
    def complete(self) -> bool:
        """Every part has its audio."""
        return all(j.status in ("done", "resumed") for j in self.jobs)

    @property
    def ok(self) -> bool:
        """Every part has its audio, and they sum to the song."""
        return self.complete and bool(self.null_test and self.null_test.passed)

    def wav(self, name: str) -> Path | None:
        j = next((j for j in self.jobs if j.job.name == name), None)
        return Path(j.wav_path) if j and j.wav_path else None

    def premaster(self) -> Path | None:
        """The mix before the Master that Eden mixes against."""
        return Path(self.premaster_sum) if self.premaster_sum else self.wav("premaster")


def sample_repairs(report: InspectionReport, allow_missing: bool = False) -> dict[int, str]:
    """Sample paths to rewrite in the copies so FL Studio finds every file."""
    repairs: dict[int, str] = {}
    missing = []
    for s in report.sources:
        if not s.sample or not s.reaches_master:
            continue
        if s.sample.status == "found_elsewhere" and s.sample.resolved_path:
            repairs[s.channel] = s.sample.resolved_path
        elif s.sample.status in ("missing", "unreadable") and not s.sample.is_factory:
            missing.append(f"{s.label} ({s.sample.stored_path})")
    if missing and not allow_missing:
        raise RenderError("Fichiers audio introuvables, le rendu serait incomplet : " + "; ".join(missing))
    return repairs


def plays_to_the_end(report: InspectionReport, channels: list[int]) -> bool:
    """Whether one of ``channels`` without reverb or delay plays until the song's very end (a beat that runs
    to it): the sound still there at the end of a render is then its own, not an echo cut short."""
    end = report.project_end_seconds
    return end is not None and any(s.channel in channels and not s.space_effects and s.last_seconds is not None
                                   and s.last_seconds >= end - END_TOLERANCE_S for s in report.sources)


def build_copy(original: bytes, job: RenderJob, repairs: dict[int, str]) -> bytes:
    ed = FlpEditor(original)
    for channel, path in repairs.items():
        ed.set_sample_path(channel, path)
    for ch in job.mute_channels:
        ed.set_channel_enabled(ch, False)
    for src, target in job.cut_routes:
        ed.set_route(src, target, False)
    for insert, slot in job.bypass_slots:
        ed.set_slot_enabled(insert, slot, False)
    if job.bypass_master_switch:
        ed.set_insert_effects_enabled(MASTER_INSERT, False)
    return ed.to_bytes()


def _write_manifest(path: Path, result: RenderResult) -> None:
    from eden.project.model import to_jsonable

    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(to_jsonable(result), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _previous(manifest: Path) -> dict[str, dict]:
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {j["job"]["name"]: j for j in data.get("jobs", []) if j.get("status") in ("done", "resumed")}


def _sum(path: Path, parts: list[Path]) -> Path:
    """The parts added up, in 32-bit float (over full scale where they go over)."""
    total: np.ndarray | None = None
    for part in parts:
        data, sr = load(part)
        if total is None:
            total = data
            continue
        if data.shape[0] > total.shape[0]:
            total = np.pad(total, ((0, data.shape[0] - total.shape[0]), (0, 0)))
        total[:data.shape[0]] += data
    sf.write(path, total, sr, subtype="FLOAT")
    return path


def _clock(seconds: float) -> str:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


def _why(result: RenderResult, summed: list[JobResult]) -> str:
    """What the difference of a failed null test is like: said to the user, and to whoever helps them."""
    test, hints = result.null_test, []
    reference = next((j.check for j in result.jobs if j.job.name == "premaster" and j.check), None)
    if reference and reference.clipped_samples and "FLOAT" not in reference.subtype.upper():
        hints.append(f"le morceau rendu sans les effets du Master sature (export WAV de FL Studio en "
                     f"{reference.subtype}) : exporte une fois ton projet en WAV 32 bits flottant dans FL "
                     "Studio, qui garde ce réglage, puis relance")
    if test.resembles is not None:
        part = next(j.job.description for j in summed if j.wav_path == test.resembles)
        hints.append(f"l'écart ressemble à « {part} »")
    elif test.resembles_mix:
        hints.append("l'écart ressemble au morceau entier (un volume qui change d'un rendu à l'autre)")
    if test.loudest:
        hints.append(f"il est surtout entre {_clock(test.loudest[0])} et {_clock(test.loudest[1])}")
    return "".join(f" ; {hint}" for hint in hints)


def render_project(
    path: str | Path,
    renderer: Renderer,
    timeout_s: float = 900.0,
    threshold_db: float = -60.0,
    allow_missing: bool = False,
    workspace_home: Path | None = None,
    report: InspectionReport | None = None,
    on_step: StepCallback | None = None,
) -> RenderResult:
    path = Path(path)
    report = report or inspect_project(path, workspace_home=workspace_home)
    original, fp = read_project_bytes(path)
    if fp.sha256 != report.file.sha256:
        raise RenderError("Le projet a changé depuis l'analyse : relance l'analyse")

    plan = plan_renders(report)
    repairs = sample_repairs(report, allow_missing)
    ws = Workspace(path, workspace_home)
    folder = ws.root / "renders" / fp.sha256[:12]
    folder.mkdir(parents=True, exist_ok=True)
    manifest = folder / "manifest.json"
    previous = _previous(manifest)

    result = RenderResult(
        project=str(path), project_sha256=fp.sha256, folder=str(folder), plan=plan, jobs=[],
        null_test=None,
        repairs=[f"canal {c} → {p}" for c, p in repairs.items()],
        warnings=list(plan.notes),
    )
    total = len(plan.jobs) + 1
    audio: dict[str, str] = {}  # copy → its audio: two parts asking for the same copy cost one render
    owner: dict[str, JobResult] = {}  # copy → the part FL renders it for
    for job in plan.jobs:
        copy_bytes = build_copy(original, job, repairs)
        copy_sha = hashlib.sha256(copy_bytes).hexdigest()
        jr = JobResult(job=job, copy_sha256=copy_sha)
        result.jobs.append(jr)
        prev = previous.get(job.name)
        if copy_sha not in audio and prev and prev.get("copy_sha256") == copy_sha and prev.get("wav_path") \
                and Path(prev["wav_path"]).is_file():  # kept from a previous run
            audio[copy_sha] = prev["wav_path"]
        if copy_sha in audio or copy_sha in owner:
            continue
        job_dir = folder / job.name
        job_dir.mkdir(exist_ok=True)
        (job_dir / f"{job.name}.flp").write_bytes(copy_bytes)
        owner[copy_sha] = jr
    copies = {folder / jr.job.name / f"{jr.job.name}.flp": sha for sha, jr in owner.items()}

    def settle(copy_sha: str) -> None:
        """The audio of a copy is there: each part asking for it is done (``resumed`` when FL did not
        render it for that part: identical copy, or kept from a previous run)."""
        check = check_audio(Path(audio[copy_sha]))
        for i, jr in enumerate(result.jobs):
            if jr.copy_sha256 != copy_sha or jr.status != "pending":
                continue
            jr.wav_path, jr.check = audio[copy_sha], check
            jr.status = "done" if owner.get(copy_sha) is jr else "resumed"
            if jr.status == "done" and check.silent and jr.job.kind not in ("original", "rest"):
                result.warnings.append(f"Rendu silencieux : {jr.job.description}")
            if on_step:
                on_step(i, total, f"{'Rendu par FL Studio' if jr.status == 'done' else 'Déjà rendu'} : "
                                  f"{jr.job.description}")
        _write_manifest(manifest, result)

    def fail(jr: JobResult, exc: Exception) -> NoReturn:
        jr.status, jr.error = "failed", str(exc)
        _write_manifest(manifest, result)
        raise RenderError(f"Échec du rendu « {jr.job.description} » : {exc}") from exc

    def rendered(copy: Path, produced: Path) -> None:
        copy_sha = copies[copy]
        target = copy.with_suffix(".wav")
        try:
            if produced != target:
                target.unlink(missing_ok=True)
                produced.replace(target)
        except OSError as exc:
            fail(owner[copy_sha], exc)
        audio[copy_sha] = str(target)
        settle(copy_sha)

    for copy_sha in list(audio):  # kept from a previous run
        settle(copy_sha)
    if on_step and copies:
        at_once = renderer.at_once(len(copies))
        on_step(-1, total, f"Rendu FL Studio : {len(copies)} rendu{'s' if len(copies) > 1 else ''} pour "
                           f"{len(plan.jobs)} parties, " + (f"{at_once} FL Studio en même temps" if at_once > 1
                                                          else "un à la fois"))
    try:
        if len(copies) > 1:  # FL renders them together, then each one it left is rendered alone
            renderer.render_many(list(copies), timeout_s, rendered)
        for copy, copy_sha in copies.items():
            if copy_sha in audio:
                continue
            try:
                produced = renderer.render(copy, timeout_s)
            except (RenderError, OSError) as exc:
                fail(owner[copy_sha], exc)
            rendered(copy, produced)
    finally:
        for copy in copies:
            copy.unlink(missing_ok=True)

    if on_step:
        on_step(len(plan.jobs), total, "Vérification : la somme des pistes reproduit-elle le mix ?")
    premaster = result.wav("premaster")
    summed = [j for j in result.jobs if j.job.kind in ("stem", "rest") and j.wav_path]
    if premaster and summed:
        result.null_test = null_test(premaster, [Path(j.wav_path) for j in summed], threshold_db)
        test = result.null_test
        if not test.passed and test.unclipped_db is not None and test.unclipped_db <= threshold_db:
            result.premaster_sum = str(_sum(folder / "premaster-somme.wav", [Path(j.wav_path) for j in summed]))
            test.passed = True
            test.message = (f"Somme des pistes = mix d'origine là où il ne sature pas (écart "
                            f"{test.unclipped_db:.1f} dB) ; rendu en WAV entier, le morceau sans les effets du "
                            "Master sature : Eden prend la somme des pistes, qui ne sature pas")
        elif not test.passed:
            test.message += _why(result, summed)

    checks = [j.check for j in result.jobs if j.check]
    if len({(c.sample_rate, c.channels) for c in checks}) > 1:
        result.warnings.append("Les rendus n'ont pas tous le même format audio")
    cut = [j.job.description for j in result.jobs if j.check and j.check.ends_with_sound
           and not plays_to_the_end(report, j.job.channels)]
    if cut:
        result.warnings.append(
            "Le son est encore présent à la toute fin de certains rendus (" + "; ".join(cut) + ") : "
            "une fin d'écho, de delay ou de reverb est peut-être coupée. Dans la fenêtre d'export "
            "de FL Studio, choisis de laisser la fin des effets (« Leave remainder »), puis "
            "relance la récupération du son.")
    if any(j.check.clipped_samples for j in result.jobs if j.check and "FLOAT" not in j.check.subtype.upper()
           and not (j.job.name == "premaster" and result.premaster_sum)):  # rebuilt from its parts: no harm
        result.warnings.append(
            "Certains rendus atteignent 0 dBFS en format entier (écrêtage possible) : "
            "règle l'export WAV de FL Studio en 32 bits flottant")
    verify_unchanged(path, fp)
    _write_manifest(manifest, result)
    return result
