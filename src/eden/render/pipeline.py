"""Get the real sound of a project out of FL Studio, automatically.

    inspection → render plan → temporary copy → FL Studio render → copy deleted
    → checks → null test (sum of stems == pre-master mix)
    → Master checks (a mix re-injected into FL's Master gives back the song)

FL Studio does all the sound: Eden only mutes parts of the project in a
temporary copy so that FL renders each part separately, with every effect
the user set (delays, Auto-Tune, echoes...). Each copy is deleted as soon as
FL has rendered it; only the audio stays, in Eden's workspace. The original
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

from eden.flp.edit import FlpEditor
from eden.project.inspector import InspectionReport, inspect_project
from eden.project.model import MASTER_INSERT
from eden.render.fl_studio import RenderError, Renderer
from eden.render.master import Calibration, measure_gain, prepare_mix_for_master, reinjection_copy
from eden.render.plan import RenderJob, RenderPlan, plan_renders
from eden.render.verify import AudioCheck, NullTest, check_audio, null_test
from eden.safety import Workspace, read_project_bytes, verify_unchanged

StepCallback = Callable[[int, int, str], None]


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
    calibration: Calibration | None = None  # gain of a channel re-injected into the Master
    master_test: NullTest | None = None  # original mix through the Master == original render

    @property
    def stems_ok(self) -> bool:
        return all(j.status in ("done", "resumed") for j in self.jobs) and bool(
            self.null_test and self.null_test.passed)

    @property
    def master_ok(self) -> bool:
        return bool(self.calibration and self.calibration.passed
                    and self.master_test and self.master_test.passed)

    @property
    def ok(self) -> bool:
        return self.stems_ok and self.master_ok

    def wav(self, name: str) -> Path | None:
        j = next((j for j in self.jobs if j.job.name == name), None)
        return Path(j.wav_path) if j and j.wav_path else None


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


def build_copy(original: bytes, job: RenderJob, repairs: dict[int, str]) -> bytes:
    ed = FlpEditor(original)
    for channel, path in repairs.items():
        ed.set_sample_path(channel, path)
    for idx in job.mute_inserts:
        ed.set_insert_enabled(idx, False)
    for ch in job.mute_channels:
        ed.set_channel_enabled(ch, False)
    for src, target in job.cut_routes:
        ed.set_route(src, target, False)
    if job.bypass_master_effects:
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
        raise RenderError("Le projet a changé depuis l'analyse : relancez l'analyse")

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
    total = len(plan.jobs) + 3

    def run(job: RenderJob, copy_bytes: bytes, step: int) -> JobResult:
        """Have FL render a temporary copy (or reuse the audio of an identical one)."""
        if on_step:
            on_step(step, total, f"Rendu FL Studio : {job.description}")
        job_dir = folder / job.name
        job_dir.mkdir(exist_ok=True)
        copy_path = job_dir / f"{job.name}.flp"
        copy_sha = hashlib.sha256(copy_bytes).hexdigest()
        jr = JobResult(job=job, copy_sha256=copy_sha)
        result.jobs.append(jr)

        prev = previous.get(job.name)
        if prev and prev.get("copy_sha256") == copy_sha and prev.get("wav_path") \
                and Path(prev["wav_path"]).is_file():
            jr.wav_path, jr.status = prev["wav_path"], "resumed"
            jr.check = check_audio(Path(jr.wav_path))
            _write_manifest(manifest, result)
            return jr

        copy_path.write_bytes(copy_bytes)
        try:
            produced = renderer.render(copy_path, timeout_s)
            target = job_dir / f"{job.name}.wav"
            if produced != target:
                if target.exists():
                    target.unlink()
                produced.replace(target)
            jr.wav_path = str(target)
            jr.check = check_audio(target)
            jr.status = "done"
            if jr.check.silent and job.kind != "original":
                result.warnings.append(f"Rendu silencieux : {job.description}")
        except (RenderError, OSError) as exc:
            jr.status, jr.error = "failed", str(exc)
            _write_manifest(manifest, result)
            raise RenderError(f"Échec du rendu « {job.description} » : {exc}") from exc
        finally:
            copy_path.unlink(missing_ok=True)
        _write_manifest(manifest, result)
        return jr

    for i, job in enumerate(plan.jobs):
        run(job, build_copy(original, job, repairs), i)

    if on_step:
        on_step(len(plan.jobs), total, "Vérification : la somme des pistes reproduit-elle le mix ?")
    premaster = result.wav("premaster")
    stems = [Path(j.wav_path) for j in result.jobs if j.job.kind == "stem" and j.wav_path]
    if premaster and stems:
        result.null_test = null_test(premaster, stems, threshold_db)

    # Master chain kept in FL Studio: check that Eden can play a mix through it.
    if premaster and result.null_test and result.null_test.passed:
        check_job = RenderJob("controle-master", "control",
                              "Contrôle : réinjection dans le Master (effets contournés)")
        jr = run(check_job, reinjection_copy(original, report, repairs, premaster, True),
                 len(plan.jobs) + 1)
        result.calibration = measure_gain(premaster, Path(jr.wav_path), threshold_db)
        if result.calibration.passed:
            control_dir = folder / "controle-eden-0"
            control_dir.mkdir(exist_ok=True)
            feed = prepare_mix_for_master(premaster, result.calibration,
                                          control_dir / "controle-eden-0-entree.wav")
            zero_job = RenderJob("controle-eden-0", "control",
                                 "Contrôle : mix d'origine repassé dans ton Master")
            try:
                jr0 = run(zero_job, reinjection_copy(original, report, repairs, feed, False),
                          len(plan.jobs) + 2)
            finally:
                feed.unlink(missing_ok=True)
            original_wav = result.wav("original")
            if original_wav:
                result.master_test = null_test(original_wav, [Path(jr0.wav_path)], threshold_db)
        else:
            result.warnings.append(result.calibration.message)

    checks = [j.check for j in result.jobs if j.check]
    if len({(c.sample_rate, c.channels) for c in checks}) > 1:
        result.warnings.append("Les rendus n'ont pas tous le même format audio")
    cut = [j.job.description for j in result.jobs if j.check and j.check.ends_with_sound]
    if cut:
        result.warnings.append(
            "Le son est encore présent à la toute fin de certains rendus (" + "; ".join(cut) + ") : "
            "une fin d'écho, de delay ou de reverb est peut-être coupée. Dans la fenêtre d'export "
            "de FL Studio, choisissez de laisser la fin des effets (« Leave remainder »), puis "
            "relancez.")
    if any(c.clipped_samples for c in checks if "FLOAT" not in c.subtype.upper()):
        result.warnings.append(
            "Certains rendus atteignent 0 dBFS en format entier (écrêtage possible) : "
            "réglez l'export WAV de FL Studio en 32 bits flottant")
    verify_unchanged(path, fp)
    _write_manifest(manifest, result)
    return result
