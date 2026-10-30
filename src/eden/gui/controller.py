"""Bridge between the QML interface and Eden's engine.

Long operations run in worker threads; the interface only reflects real
progress reported by the engine and real outcomes (no simulated progress).

Once a project is chosen, Eden goes all the way in one go (the "journey"): analysis, FL Studio's
renders, the mix, the master. The interface shows it as a tree growing in a garden: ``growth``
(0 → 1) follows the real steps of each stage on the stages of the tree (see ``garden.py``), and a
journal says in French what is happening. When the work is done (``journeyFinished``), the
interface plays the end (an apple grows and falls) and calls ``endJourney`` to show the result.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Property, QThread, QUrl, Signal, Slot, QObject
from PySide6.QtGui import QDesktopServices

from eden import __version__
from eden.gui import viewmodel
from eden.gui.player import ABPlayer
from eden.project.inspector import InspectionError, InspectionReport, inspect_project

ASSETS = Path(__file__).resolve().parent.parent / "assets"

# the stages of the journey: (key, what the garden shows, share of the tree's growth: from, to)
JOURNEY = (
    ("analysis", "Analyse du projet", 0.0, 0.08),
    ("render", "FL Studio joue tes pistes", 0.08, 0.40),
    ("mix", "Mixage Eden", 0.40, 0.82),
    ("master", "Mastering Eden", 0.82, 0.97),
    ("checks", "Vérification et sauvegarde", 0.97, 1.0),
)
SPANS = {key: (start, end) for key, _, start, end in JOURNEY}
# the mix session's steps, as stages of the journey
MIX_STAGES = ("mix", "mix", "master", "checks")
LOG_LIMIT = 2000  # lines kept for a view opened late (the garden is shown during the whole journey)


def default_renderer():
    """FL Studio renderer from the saved settings, or None if not set up yet."""
    from eden.render.fl_studio import FLStudioRenderer, find_fl_studio
    from eden.settings import load_settings

    settings = load_settings()
    exe = find_fl_studio(settings.fl_path)
    if exe is None or not settings.render_args:
        return None
    return FLStudioRenderer([str(exe)], settings.render_args)


def default_export_folder() -> Path:
    music = Path.home() / "Music"
    return music if music.is_dir() else Path.home()


def _projects_folder() -> str:
    """The folder the user chose for their FL projects, else FL Studio's own when it exists."""
    from eden.project.library import default_projects_folder
    from eden.settings import load_settings

    chosen = load_settings().projects_folder
    if chosen:
        return chosen
    found = default_projects_folder()
    return str(found) if found else ""


def default_probe(path: Path, log: Callable[[str], None]):
    from eden.render.probe import probe_fl_studio

    return probe_fl_studio(path, log=log)


class _Worker(QThread):
    progress = Signal(int, int, str)
    detail = Signal(str, float)  # what is being done, share of the running step done (-1: a detail)
    log = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str, str)

    def __init__(self, fn) -> None:
        super().__init__()
        self.fn = fn

    def run(self) -> None:
        try:
            self.succeeded.emit(self.fn(self))
        except InspectionError as exc:
            self.failed.emit(exc.step, exc.message)
        except _StepError as exc:
            self.failed.emit(exc.step, exc.message)
        except Exception as exc:  # still tell the user which operation failed
            self.failed.emit("Erreur inattendue", f"{type(exc).__name__}: {exc}")


class _StepError(Exception):
    def __init__(self, step: str, message: str) -> None:
        super().__init__(message)
        self.step, self.message = step, message


class EdenController(QObject):
    stageChanged = Signal()
    busyChanged = Signal()
    projectPathChanged = Signal()
    projectNameChanged = Signal()
    errorStepChanged = Signal()
    errorMessageChanged = Signal()
    reportChanged = Signal()
    renderRowsChanged = Signal()
    renderSummaryChanged = Signal()
    probeLogChanged = Signal()
    needsFlPathChanged = Signal()
    updateMessageChanged = Signal()
    intensityChanged = Signal()
    mixResultChanged = Signal()
    mixVersionsChanged = Signal()
    exportFolderChanged = Signal()
    exportMessageChanged = Signal()
    projectsFolderChanged = Signal()
    projectsChanged = Signal()
    projectsMessageChanged = Signal()
    journeyActiveChanged = Signal()
    journeyFinishedChanged = Signal()
    growthChanged = Signal()
    journeyStageChanged = Signal()
    journeyStepChanged = Signal()
    journeyStagesChanged = Signal()
    logAdded = Signal("QVariantMap")  # one new line of the journal: {time, text, kind}
    logCleared = Signal()  # a new journey: the journal starts again

    def __init__(self, renderer_factory=None, probe=None, check_updates: bool = True,
                 player: ABPlayer | None = None) -> None:
        super().__init__()
        # home | analyzing | analyzed | rendering | rendered | mixing | mixed
        self._stage = "home"
        self._busy = False
        self._projectPath = ""
        self._projectName = ""
        self._errorStep = ""
        self._errorMessage = ""
        self._report: dict = {}
        self._renderRows: list = []
        self._renderSummary: dict = {}
        self._probeLog: list = []
        self._needsFlPath = False
        self._updateMessage = ""
        self._intensity = 1.0
        self._mixResult: dict = {}
        self._mixVersions: list = []
        self._exportFolder = str(default_export_folder())
        self._exportMessage = ""
        self._projectsFolder = _projects_folder()
        self._projects: list = []
        self._projectsMessage = ""
        self._journeyActive = False
        self._journeyFinished = False
        self._growth = 0.0
        self._journeyStage = ""
        self._journeyStep = ""
        self._journeyStages: list = []
        self._journeyLog: list = []
        self._journey_started = 0.0
        self._mix_stage = "mix"  # the journey stage of the mix session's running step
        self.report_obj: InspectionReport | None = None
        self.renders = None  # RenderResult of the current project
        self.renderer_factory = renderer_factory or default_renderer
        self.probe = probe or default_probe
        self.worker: _Worker | None = None
        self.update_worker: _Worker | None = None
        self._player = player or ABPlayer()
        self.refreshProjects()
        if check_updates:
            self._start_update_check()

    # -- properties exposed to QML ------------------------------------------
    stage = Property(str, lambda self: self._stage, notify=stageChanged)
    busy = Property(bool, lambda self: self._busy, notify=busyChanged)
    projectPath = Property(str, lambda self: self._projectPath, notify=projectPathChanged)
    projectName = Property(str, lambda self: self._projectName, notify=projectNameChanged)
    errorStep = Property(str, lambda self: self._errorStep, notify=errorStepChanged)
    errorMessage = Property(str, lambda self: self._errorMessage, notify=errorMessageChanged)
    report = Property("QVariantMap", lambda self: self._report, notify=reportChanged)
    renderRows = Property("QVariantList", lambda self: self._renderRows, notify=renderRowsChanged)
    renderSummary = Property("QVariantMap", lambda self: self._renderSummary, notify=renderSummaryChanged)
    probeLog = Property("QVariantList", lambda self: self._probeLog, notify=probeLogChanged)
    needsFlPath = Property(bool, lambda self: self._needsFlPath, notify=needsFlPathChanged)
    updateMessage = Property(str, lambda self: self._updateMessage, notify=updateMessageChanged)
    mixResult = Property("QVariantMap", lambda self: self._mixResult, notify=mixResultChanged)
    mixVersions = Property("QVariantList", lambda self: self._mixVersions, notify=mixVersionsChanged)
    exportFolder = Property(str, lambda self: self._exportFolder, notify=exportFolderChanged)
    exportMessage = Property(str, lambda self: self._exportMessage, notify=exportMessageChanged)
    projectsFolder = Property(str, lambda self: self._projectsFolder, notify=projectsFolderChanged)
    projectsFolderUrl = Property(str, lambda self: QUrl.fromLocalFile(self._projectsFolder).toString()
                                 if self._projectsFolder else "", notify=projectsFolderChanged)
    projects = Property("QVariantList", lambda self: self._projects, notify=projectsChanged)
    projectsMessage = Property(str, lambda self: self._projectsMessage, notify=projectsMessageChanged)
    journeyActive =Property(bool, lambda self: self._journeyActive, notify=journeyActiveChanged)
    journeyFinished = Property(bool, lambda self: self._journeyFinished, notify=journeyFinishedChanged)
    growth = Property(float, lambda self: self._growth, notify=growthChanged)
    journeyStage = Property(str, lambda self: self._journeyStage, notify=journeyStageChanged)
    journeyStep = Property(str, lambda self: self._journeyStep, notify=journeyStepChanged)
    journeyStages = Property("QVariantList", lambda self: self._journeyStages, notify=journeyStagesChanged)
    player = Property(QObject, lambda self: self._player, constant=True)

    @Slot(result="QVariantList")
    def journeyLines(self) -> list[dict]:
        """The journal so far, for a view opened during the journey (then ``logAdded``)."""
        return list(self._journeyLog)

    def _get_intensity(self) -> float:
        return self._intensity

    def _set_intensity(self, value: float) -> None:
        self._set("intensity", max(0.0, min(1.0, float(value))))

    intensity = Property(float, _get_intensity, _set_intensity, notify=intensityChanged)

    @Property(str, constant=True)
    def version(self) -> str:
        return __version__

    @Property("QVariantList", constant=True)
    def treeTriangles(self) -> list:
        try:
            data = json.loads((ASSETS / "tree.json").read_text(encoding="utf-8"))
        except OSError:
            return []
        return data["triangles"]

    @Property("QVariantList", constant=True)
    def sampleRates(self) -> list:
        return viewmodel.sample_rate_choices()

    @Property(str, constant=True)
    def logoUrl(self) -> str:
        return QUrl.fromLocalFile(str(ASSETS / "eden-logo.png")).toString()

    def _set(self, name: str, value) -> None:
        if getattr(self, f"_{name}") != value:
            setattr(self, f"_{name}", value)
            getattr(self, f"{name}Changed").emit()

    def _start(self, fn, on_success, on_progress=None, on_detail=None) -> None:
        self._set("errorStep", "")
        self._set("errorMessage", "")
        self._set("busy", True)
        self.worker = _Worker(fn)
        if on_progress:
            self.worker.progress.connect(on_progress)
        if on_detail:
            self.worker.detail.connect(on_detail)
        self.worker.log.connect(self._on_log)
        self.worker.succeeded.connect(on_success)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_failed(self, step: str, message: str) -> None:
        self._set("busy", False)
        if step == "Recherche de FL Studio":
            self._set("needsFlPath", True)
        self._set("errorStep", step)
        self._set("errorMessage", message)
        self._log(f"Échec à l'étape « {step} » : {message}", "error")
        self._set("journeyActive", False)
        if self._stage == "analyzing":
            self._set("stage", "home")
        elif self._stage == "rendering":
            self._set("stage", "analyzed")
        elif self._stage == "mixing":
            self._set("stage", "mixed" if self._mixResult else "rendered")

    def _on_log(self, line: str) -> None:
        self._set("probeLog", [*self._probeLog, line])
        self._log(line, "detail")

    # -- the journey: one growth from the seed to the apple ----------------------------------
    def _begin_journey(self, stage: str, fresh: bool) -> None:
        """Show the garden; ``fresh``: a new journey (journal emptied, the tree from the start of
        ``stage``), else the journey resumes where it stopped."""
        if fresh:
            self._journey_started = time.monotonic()
            self._journeyLog = []
            self.logCleared.emit()
            self._set("journeyStage", "")
            self._set("growth", SPANS[stage][0])
        self._set("journeyFinished", False)
        self._set("journeyActive", True)

    def _enter(self, stage: str) -> None:
        """The journey reaches ``stage``: the stages before it are done."""
        if stage == self._journeyStage:
            return
        self._set("journeyStage", stage)
        order = [key for key, *_ in JOURNEY]
        here = order.index(stage)
        self._set("journeyStages", [{"key": key, "label": label,
                                     "status": "done" if i < here else "running" if i == here else "pending"}
                                    for i, (key, label, *_) in enumerate(JOURNEY)])
        self._grow(stage, 0.0)
        self._log(dict((k, label) for k, label, *_ in JOURNEY)[stage], "stage")

    def _grow(self, stage: str, share: float) -> None:
        """The tree reaches ``share`` of ``stage``'s span (it never shrinks during a journey)."""
        start, end = SPANS[stage]
        self._set("growth", max(self._growth, start + (end - start) * max(0.0, min(1.0, share))))

    def _step(self, text: str) -> None:
        self._set("journeyStep", text)
        self._log(text, "step")

    def _log(self, text: str, kind: str) -> None:
        elapsed = int(time.monotonic() - self._journey_started) if self._journey_started else 0
        line = {"time": f"{elapsed // 60:02d}:{elapsed % 60:02d}", "text": text, "kind": kind}
        self._journeyLog = [*self._journeyLog[-(LOG_LIMIT - 1):], line]
        self.logAdded.emit(line)

    @Slot()
    def endJourney(self) -> None:
        """The interface has played the end of the journey: the result is shown."""
        self._set("journeyActive", False)
        self._set("journeyFinished", False)

    # -- the user's projects --------------------------------------------------------------------
    @Slot(str)
    def setProjectsFolder(self, url: str) -> None:
        """The folder where the user saves FL projects, kept for the next times."""
        from eden.settings import load_settings, save_settings

        folder = str(Path(QUrl(url).toLocalFile() if "://" in url else url))
        settings = load_settings()
        settings.projects_folder = folder
        save_settings(settings)
        self._set("projectsFolder", folder)
        self.refreshProjects()

    @Slot()
    def refreshProjects(self) -> None:
        """The projects of the folder as they are now (called each time the home page is shown)."""
        from eden.project.library import find_projects

        folder = Path(self._projectsFolder) if self._projectsFolder else None
        rows, message = [], ""
        if folder is None:
            pass  # the page asks for the folder
        elif not folder.is_dir():
            message = "Ce dossier est introuvable (renommé, déplacé, ou sur un disque débranché) : choisis où sont tes projets."
        else:
            rows = viewmodel.project_rows(find_projects(folder), time.time())
            if not rows:
                message = "Aucun projet FL Studio (.flp) dans ce dossier ni ses sous-dossiers."
        self._set("projects", rows)
        self._set("projectsMessage", message)

    # -- project & analysis -------------------------------------------------------
    @Slot(str)
    def openProject(self, url: str) -> None:
        path = Path(QUrl(url).toLocalFile() if "://" in url else url)
        if self._busy:
            return
        self._set("projectPath", str(path))
        self._set("projectName", path.stem)
        self.report_obj = None
        self.renders = None
        self._set("report", {})
        self._set("renderRows", [])
        self._set("renderSummary", {})
        self._set("mixResult", {})
        self._set("mixVersions", [])
        self._set("exportMessage", "")
        self._player.close()
        self._begin_journey("analysis", fresh=True)
        self._analyze()

    def _analyze(self) -> None:
        path = Path(self._projectPath)
        self._set("stage", "analyzing")
        self._enter("analysis")

        def job(worker: _Worker):
            return inspect_project(path, on_step=lambda i, n, s: worker.progress.emit(i, n, s))

        self._start(job, self._on_analyzed, self._on_analysis_progress)

    def _on_analysis_progress(self, index: int, total: int, label: str) -> None:
        self._grow("analysis", index / total)
        self._step(label)

    def _on_analyzed(self, report: InspectionReport) -> None:
        self.report_obj = report
        self._set("report", viewmodel.report_view(report))
        for text, kind in viewmodel.analysis_lines(self._report):
            self._log(text, kind)
        self._grow("analysis", 1.0)
        self._set("busy", False)
        self._set("stage", "analyzed")
        self.renderFromFl()

    # -- getting the sound out of FL Studio --------------------------------
    @Slot()
    def renderFromFl(self) -> None:
        if self.report_obj is None or self._busy:
            return
        from eden.render.plan import plan_renders

        report = self.report_obj
        path = Path(self._projectPath)
        self._set("renderRows", viewmodel.render_rows(plan_renders(report)))
        self._set("renderSummary", {})
        self._set("probeLog", [])
        # right after the analysis (or once FL Studio is found) the journey goes on; asked again
        # from a page, the tree grows again from where FL Studio's renders start
        self._begin_journey("render", fresh=self._stage != "analyzed")
        self._set("stage", "rendering")
        self._enter("render")
        renderer_factory, probe = self.renderer_factory, self.probe

        def job(worker: _Worker):
            from eden.render.fl_studio import RenderError, find_fl_studio
            from eden.render.pipeline import render_project
            from eden.settings import load_settings

            renderer = renderer_factory()
            if renderer is None:
                if renderer_factory is default_renderer and find_fl_studio(load_settings().fl_path) is None:
                    raise _StepError("Recherche de FL Studio", "FL Studio introuvable sur ce PC")
                worker.progress.emit(0, 1, "Première utilisation : Eden apprend à piloter FL Studio…")
                result = probe(path, log=worker.log.emit)
                renderer = renderer_factory() if result.ok else None
                if renderer is None:
                    raise _StepError("Configuration de FL Studio",
                                     result.lines[-1] if result.lines else "échec du test")
            settings = load_settings()
            try:
                return render_project(path, renderer, timeout_s=settings.render_timeout_s,
                                      threshold_db=settings.null_test_threshold_db, report=report,
                                      on_step=lambda i, n, s: worker.progress.emit(i, n, s))
            except RenderError as exc:
                raise _StepError("Rendu FL Studio", str(exc)) from exc

        self._start(job, self._on_rendered, self._on_render_progress)

    def _on_render_progress(self, index: int, total: int, label: str) -> None:
        self._step(label)
        if total > 1 and self._renderRows:
            self._grow("render", index / total)
            self._set("renderRows", viewmodel.mark_step(self._renderRows, index))

    def _on_rendered(self, result) -> None:
        self.renders = result
        rows, summary = viewmodel.render_view(self._renderRows, result)
        self._set("renderRows", rows)
        self._set("renderSummary", summary)
        for text, kind in viewmodel.render_lines(rows, summary):
            self._log(text, kind)
        self._set("busy", False)
        self._set("stage", "rendered")
        if result.ok:
            self._grow("render", 1.0)
            self.mixProject()
        else:  # the renders did not pass their checks: the render page says why
            self._log("Le son récupéré n'a pas passé ses vérifications : Eden s'arrête là", "error")
            self._set("journeyActive", False)

    # -- Eden's mix and master, export ---------------------------------------------
    @Slot()
    def mixProject(self) -> None:
        if self._busy or self.report_obj is None or self.renders is None or not self.renders.ok:
            return
        from eden.mix.session import MixError, mix_project

        project, report, renders = Path(self._projectPath), self.report_obj, self.renders
        intensity = self._intensity
        self._set("exportMessage", "")
        self._player.close()
        # a remix grows the tree again from where the mix starts
        self._begin_journey("mix", fresh=self._stage == "mixed")
        self._set("stage", "mixing")
        self._enter("mix")
        self._load_versions()

        def job(worker: _Worker):
            try:
                return mix_project(project, report, renders, intensity,
                                   on_step=lambda i, n, s: worker.progress.emit(i, n, s),
                                   on_progress=lambda s, share: worker.detail.emit(s, -1.0 if share is None
                                                                                   else share))
            except MixError as exc:
                raise _StepError("Mixage Eden", str(exc)) from exc

        self._start(job, self._on_mixed, self._on_mix_step, self._on_mix_detail)

    def _on_mix_step(self, index: int, total: int, label: str) -> None:
        self._mix_stage = MIX_STAGES[index]
        self._enter(self._mix_stage)
        if index in (0, len(MIX_STAGES) - 1):  # the mix and the master tell their own steps
            self._step(label)

    def _on_mix_detail(self, text: str, share: float) -> None:
        if share < 0:
            self._log(text, "detail")
            return
        self._grow(self._mix_stage, share)
        self._step(text)

    def _on_mixed(self, version) -> None:
        self._set("mixResult", viewmodel.mix_view(json.loads(version.to_json())))
        self._listen()
        for text, kind in viewmodel.mix_lines(self._mixResult):
            self._log(text, kind)
        self._load_versions()
        self._set("growth", 1.0)
        self._set("journeyStages", [{**s, "status": "done"} for s in self._journeyStages])
        self._step("Terminé : ton morceau est mixé et masterisé")
        self._set("busy", False)
        self._set("stage", "mixed")
        self._set("journeyFinished", True)

    def _load_versions(self) -> None:
        from eden.mix.session import list_versions

        self._set("mixVersions", viewmodel.versions_view(list_versions(Path(self._projectPath))))

    @Slot(str)
    def showVersion(self, version_id: str) -> None:
        """Bring back an earlier mix (its decisions and its final WAV)."""
        from eden.mix.session import list_versions

        for data in list_versions(Path(self._projectPath)):
            if data["id"] == version_id:
                self._set("mixResult", viewmodel.mix_view(data))
                self._set("exportMessage", "")
                self._listen()
                return

    def _listen(self) -> None:
        """The player compares the version shown with the song as FL Studio renders it."""
        r = self._mixResult
        self._player.open(r.get("originalWav", ""), r.get("finalWav", ""),
                          (r["loudness"]["original"], r["loudness"]["final"]) if "loudness" in r else (None, None))

    @Slot(str)
    def setExportFolder(self, url: str) -> None:
        self._set("exportFolder", QUrl(url).toLocalFile() if "://" in url else url)

    @Slot(str, int, int)
    def exportWav(self, name: str, sample_rate: int, bit_depth: int) -> None:
        source = self._mixResult.get("finalWav")
        if self._busy or not source:
            return
        from eden.mix.export import ExportError, export_wav

        name = name.strip() or f"{self._projectName} - Eden"
        destination = Path(self._exportFolder) / name
        stage = self._stage

        def job(_worker: _Worker):
            try:
                return export_wav(Path(source), destination, sample_rate or None, bit_depth)
            except ExportError as exc:
                raise _StepError("Export du WAV", str(exc)) from exc

        def done(result) -> None:
            self._set("busy", False)
            self._set("stage", stage)
            self._set("exportMessage", viewmodel.export_message(result))

        self._set("exportMessage", "")
        self._start(job, done)

    @Slot()
    def openExportFolder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._exportFolder))

    @Slot(str)
    def setFlStudioPath(self, url: str) -> None:
        from eden.settings import load_settings, save_settings

        path = Path(QUrl(url).toLocalFile() if "://" in url else url)
        settings = load_settings()
        settings.fl_path = str(path)
        settings.render_args = None  # syntax must be re-checked for this executable
        save_settings(settings)
        self._set("needsFlPath", False)
        self._set("errorStep", "")
        self._set("errorMessage", "")

    # -- misc -----------------------------------------------------------------------
    @Slot()
    def clearError(self) -> None:
        self._set("errorStep", "")
        self._set("errorMessage", "")

    @Slot()
    def openRenderFolder(self) -> None:
        folder = self._renderSummary.get("folder")
        if folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    @Slot()
    def goHome(self) -> None:
        if not self._busy:
            self._set("stage", "home")

    def _start_update_check(self) -> None:
        def job(_worker):
            from eden.updater import check_and_download

            return check_and_download()

        self.update_worker = _Worker(job)
        self.update_worker.succeeded.connect(self._on_update)
        self.update_worker.start()

    def _on_update(self, result) -> None:
        if result.status in ("downloaded", "available_no_installer"):
            suffix = " Elle s'installera à la fermeture d'Eden." if result.status == "downloaded" else ""
            self._set("updateMessage", result.message + "." + suffix)

    def shutdown(self) -> None:
        self._player.close()
        for w in (self.worker, self.update_worker):
            if w is not None and w.isRunning():
                w.wait(3000)
        from eden.updater import launch_pending_install

        launch_pending_install()
