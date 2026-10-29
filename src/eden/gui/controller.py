"""Bridge between the QML interface and Eden's engine.

Long operations run in worker threads; the interface only reflects real
progress reported by the engine and real outcomes (no simulated progress).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Property, QObject, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices

from eden import __version__
from eden.gui import viewmodel
from eden.project.inspector import STEPS, InspectionError, InspectionReport, inspect_project

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def default_renderer():
    """FL Studio renderer from the saved settings, or None if not set up yet."""
    from eden.render.fl_studio import FLStudioRenderer, find_fl_studio
    from eden.settings import load_settings

    settings = load_settings()
    exe = find_fl_studio(settings.fl_path)
    if exe is None or not settings.render_args:
        return None
    return FLStudioRenderer([str(exe)], settings.render_args)


def default_probe(path: Path, log: Callable[[str], None]):
    from eden.render.probe import probe_fl_studio

    return probe_fl_studio(path, log=log)


class _Worker(QThread):
    progress = Signal(int, int, str)
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
    progressChanged = Signal()
    progressLabelChanged = Signal()
    projectPathChanged = Signal()
    projectNameChanged = Signal()
    errorStepChanged = Signal()
    errorMessageChanged = Signal()
    reportChanged = Signal()
    analysisStepsChanged = Signal()
    renderRowsChanged = Signal()
    renderSummaryChanged = Signal()
    probeLogChanged = Signal()
    needsFlPathChanged = Signal()
    updateMessageChanged = Signal()

    def __init__(self, renderer_factory=None, probe=None, check_updates: bool = True) -> None:
        super().__init__()
        self._stage = "home"  # home | analyzing | analyzed | rendering | rendered
        self._busy = False
        self._progress = 0.0
        self._progressLabel = ""
        self._projectPath = ""
        self._projectName = ""
        self._errorStep = ""
        self._errorMessage = ""
        self._report: dict = {}
        self._analysisSteps: list = [{"label": s, "status": "pending"} for s in STEPS]
        self._renderRows: list = []
        self._renderSummary: dict = {}
        self._probeLog: list = []
        self._needsFlPath = False
        self._updateMessage = ""
        self.report_obj: InspectionReport | None = None
        self.render_result = None
        self.renderer_factory = renderer_factory or default_renderer
        self.probe = probe or default_probe
        self.worker: _Worker | None = None
        self.update_worker: _Worker | None = None
        if check_updates:
            self._start_update_check()

    # -- properties exposed to QML ------------------------------------------
    stage = Property(str, lambda self: self._stage, notify=stageChanged)
    busy = Property(bool, lambda self: self._busy, notify=busyChanged)
    progress = Property(float, lambda self: self._progress, notify=progressChanged)
    progressLabel = Property(str, lambda self: self._progressLabel, notify=progressLabelChanged)
    projectPath = Property(str, lambda self: self._projectPath, notify=projectPathChanged)
    projectName = Property(str, lambda self: self._projectName, notify=projectNameChanged)
    errorStep = Property(str, lambda self: self._errorStep, notify=errorStepChanged)
    errorMessage = Property(str, lambda self: self._errorMessage, notify=errorMessageChanged)
    report = Property("QVariantMap", lambda self: self._report, notify=reportChanged)
    analysisSteps = Property("QVariantList", lambda self: self._analysisSteps, notify=analysisStepsChanged)
    renderRows = Property("QVariantList", lambda self: self._renderRows, notify=renderRowsChanged)
    renderSummary = Property("QVariantMap", lambda self: self._renderSummary, notify=renderSummaryChanged)
    probeLog = Property("QVariantList", lambda self: self._probeLog, notify=probeLogChanged)
    needsFlPath = Property(bool, lambda self: self._needsFlPath, notify=needsFlPathChanged)
    updateMessage = Property(str, lambda self: self._updateMessage, notify=updateMessageChanged)

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

    @Property(str, constant=True)
    def logoUrl(self) -> str:
        return QUrl.fromLocalFile(str(ASSETS / "eden-logo.png")).toString()

    def _set(self, name: str, value) -> None:
        if getattr(self, f"_{name}") != value:
            setattr(self, f"_{name}", value)
            getattr(self, f"{name}Changed").emit()

    def _start(self, fn, on_success, on_progress=None) -> None:
        self._set("errorStep", "")
        self._set("errorMessage", "")
        self._set("busy", True)
        self.worker = _Worker(fn)
        if on_progress:
            self.worker.progress.connect(on_progress)
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
        if self._stage == "analyzing":
            self._set("stage", "home")
        elif self._stage == "rendering":
            self._set("stage", "analyzed")

    def _on_log(self, line: str) -> None:
        self._set("probeLog", [*self._probeLog, line])
        self._set("progressLabel", line)

    # -- project & analysis -------------------------------------------------------
    @Slot(str)
    def openProject(self, url: str) -> None:
        path = Path(QUrl(url).toLocalFile() if "://" in url else url)
        if self._busy:
            return
        self._set("projectPath", str(path))
        self._set("projectName", path.stem)
        self.report_obj = None
        self._set("report", {})
        self._set("renderRows", [])
        self._set("renderSummary", {})
        self.analyze()

    @Slot()
    def analyze(self) -> None:
        if not self._projectPath or self._busy:
            return
        path = Path(self._projectPath)
        self._set("stage", "analyzing")
        self._set("progress", 0.0)
        self._set("analysisSteps", [{"label": s, "status": "pending"} for s in STEPS])

        def job(worker: _Worker):
            return inspect_project(path, on_step=lambda i, n, s: worker.progress.emit(i, n, s))

        self._start(job, self._on_analyzed, self._on_analysis_progress)

    def _on_analysis_progress(self, index: int, total: int, label: str) -> None:
        self._set("progress", index / total)
        self._set("progressLabel", label)
        self._set("analysisSteps", [
            {"label": s, "status": "done" if i < index else "running" if i == index else "pending"}
            for i, s in enumerate(STEPS)
        ])

    def _on_analyzed(self, report: InspectionReport) -> None:
        self.report_obj = report
        self._set("analysisSteps", [{"label": s, "status": "done"} for s in STEPS])
        self._set("progress", 1.0)
        self._set("progressLabel", "")
        self._set("report", viewmodel.report_view(report))
        self._set("busy", False)
        self._set("stage", "analyzed")

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
        self._set("progress", 0.0)
        self._set("stage", "rendering")
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
        self._set("progressLabel", label)
        if total > 1 and self._renderRows:
            self._set("progress", index / total)
            self._set("renderRows", viewmodel.mark_step(self._renderRows, index))

    def _on_rendered(self, result) -> None:
        self.render_result = result
        rows, summary = viewmodel.render_view(self._renderRows, result)
        self._set("renderRows", rows)
        self._set("renderSummary", summary)
        self._set("progress", 1.0)
        self._set("progressLabel", "Terminé : tout a été vérifié." if result.ok else
                  "Terminé, avec des points à vérifier (voir ci-dessous).")
        self._set("busy", False)
        self._set("stage", "rendered")

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
        for w in (self.worker, self.update_worker):
            if w is not None and w.isRunning():
                w.wait(3000)
        from eden.updater import launch_pending_install

        launch_pending_install()
