"""Eden main window (PySide6).

Only features that really work are exposed: at this stage, project selection
and read-only inspection. Mixing, listening and WAV export will be added
when their engines exist.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from eden import __version__
from eden.project.inspector import InspectionError, InspectionReport, inspect_project
from eden.project.plugins import CATEGORY_LABELS_FR
from eden.report import render_markdown

STYLE = """
QWidget { background: #15171c; color: #e6e8ee; font-size: 13px; }
QLabel#title { font-size: 24px; font-weight: 600; }
QLabel#subtitle, QLabel#path { color: #9aa1b2; }
QLabel#error { color: #ff8a8a; }
QLabel#banner { background: #23324a; border-radius: 6px; padding: 8px; }
QPushButton { background: #2a2f3a; border: 1px solid #3a4150; border-radius: 6px; padding: 8px 14px; }
QPushButton:hover { background: #343b49; }
QPushButton:disabled { color: #636a7a; }
QPushButton#primary { background: #3d6df2; border-color: #3d6df2; }
QPushButton#primary:disabled { background: #2a2f3a; border-color: #3a4150; }
QProgressBar { border: 1px solid #3a4150; border-radius: 6px; text-align: center; height: 18px; }
QProgressBar::chunk { background: #3d6df2; border-radius: 5px; }
QTreeWidget, QTextBrowser { background: #1b1e25; border: 1px solid #2c313c; border-radius: 6px; }
QHeaderView::section { background: #20242c; padding: 4px; border: none; }
QTabBar::tab { background: #20242c; padding: 8px 14px; border-top-left-radius: 6px; border-top-right-radius: 6px; }
QTabBar::tab:selected { background: #2a2f3a; }
"""


class InspectWorker(QThread):
    progress = Signal(int, int, str)
    done = Signal(object)
    failed = Signal(str, str)

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path

    def run(self) -> None:
        try:
            report = inspect_project(self.path, on_step=lambda i, n, s: self.progress.emit(i, n, s))
        except InspectionError as exc:
            self.failed.emit(exc.step, exc.message)
        except Exception as exc:  # unexpected bug: still report which step failed
            self.failed.emit("Erreur inattendue", f"{type(exc).__name__}: {exc}")
        else:
            self.done.emit(report)


def default_renderer():
    """FL Studio renderer from the saved settings, or None if not probed yet."""
    from eden.render.fl_studio import FLStudioRenderer, find_fl_studio
    from eden.settings import load_settings

    settings = load_settings()
    exe = find_fl_studio(settings.fl_path)
    if exe is None or not settings.render_args:
        return None
    return FLStudioRenderer([str(exe)], settings.render_args)


class RenderWorker(QThread):
    """Probe FL Studio if needed, then render every part of the project."""

    progress = Signal(int, int, str)
    log = Signal(str)
    done = Signal(object)
    failed = Signal(str, str)

    def __init__(self, path: Path, report: InspectionReport, renderer_factory, probe) -> None:
        super().__init__()
        self.path, self.report = path, report
        self.renderer_factory, self.probe = renderer_factory, probe

    def run(self) -> None:
        from eden.render.fl_studio import RenderError
        from eden.render.pipeline import render_project
        from eden.settings import load_settings

        try:
            renderer = self.renderer_factory()
            if renderer is None:
                self.progress.emit(0, 1, "Configuration du pilotage de FL Studio (première fois)")
                result = self.probe(self.path, log=self.log.emit)
                if not result.ok:
                    self.failed.emit("Configuration de FL Studio", " ".join(result.lines[-2:]))
                    return
                renderer = self.renderer_factory()
                if renderer is None:
                    self.failed.emit("Configuration de FL Studio", "réglages introuvables après le test")
                    return
            settings = load_settings()
            result = render_project(
                self.path, renderer, timeout_s=settings.render_timeout_s,
                threshold_db=settings.null_test_threshold_db, report=self.report,
                on_step=lambda i, n, s: self.progress.emit(i, n, s),
            )
        except RenderError as exc:
            self.failed.emit("Rendu FL Studio", str(exc))
        except Exception as exc:
            self.failed.emit("Erreur inattendue", f"{type(exc).__name__}: {exc}")
        else:
            self.done.emit(result)


class UpdateWorker(QThread):
    finished_check = Signal(object)

    def run(self) -> None:
        from eden.updater import check_and_download

        self.finished_check.emit(check_and_download())


class MainWindow(QMainWindow):
    def __init__(self, check_updates: bool = True, renderer_factory=None, probe=None) -> None:
        super().__init__()
        if probe is None:
            from eden.render.probe import probe_fl_studio as probe
        self.renderer_factory = renderer_factory or default_renderer
        self.probe = probe
        self.render_worker: RenderWorker | None = None
        self.render_result = None
        self.setWindowTitle(f"Eden {__version__}")
        self.resize(1100, 720)
        self.project_path: Path | None = None
        self.report: InspectionReport | None = None
        self.worker: InspectWorker | None = None
        self.update_worker: UpdateWorker | None = None

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        title = QLabel("Eden")
        title.setObjectName("title")
        subtitle = QLabel("Mixage automatique de voix rap pour vos projets FL Studio")
        subtitle.setObjectName("subtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.banner = QLabel()
        self.banner.setObjectName("banner")
        self.banner.setWordWrap(True)
        self.banner.hide()
        layout.addWidget(self.banner)

        row = QHBoxLayout()
        self.btn_select = QPushButton("Sélectionner un projet FL Studio")
        self.btn_select.clicked.connect(self.choose_project)
        self.btn_analyze = QPushButton("Analyser le projet")
        self.btn_analyze.setObjectName("primary")
        self.btn_analyze.setEnabled(False)
        self.btn_analyze.clicked.connect(self.start_analysis)
        self.btn_render = QPushButton("Récupérer le son depuis FL Studio")
        self.btn_render.setObjectName("primary")
        self.btn_render.setEnabled(False)
        self.btn_render.setToolTip(
            "Eden ouvre FL Studio en arrière-plan sur des copies du projet et récupère "
            "chaque groupe de pistes avec ses effets. Le projet original n'est pas modifié."
        )
        self.btn_render.clicked.connect(self.start_render)
        row.addWidget(self.btn_select)
        row.addWidget(self.btn_analyze)
        row.addWidget(self.btn_render)
        row.addStretch(1)
        layout.addLayout(row)

        self.path_label = QLabel("Aucun projet sélectionné")
        self.path_label.setObjectName("path")
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.path_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setFormat("")
        layout.addWidget(self.progress)
        self.status = QLabel("")
        layout.addWidget(self.status)
        self.error = QLabel("")
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)

        self.tabs = QTabWidget()
        self.sources_tree = QTreeWidget()
        self.sources_tree.setHeaderLabels(
            ["Source", "Rôle détecté", "Confiance", "Insert", "Effets déjà présents", "Fichier"]
        )
        self.mixer_tree = QTreeWidget()
        self.mixer_tree.setHeaderLabels(["Insert", "Nom", "Volume", "Effets", "Sorties"])
        for tree in (self.sources_tree, self.mixer_tree):
            tree.header().setSectionResizeMode(QHeaderView.ResizeToContents)
            tree.setAlternatingRowColors(False)
        self.report_view = QTextBrowser()
        self.tabs.addTab(self.sources_tree, "Pistes détectées")
        self.tabs.addTab(self.mixer_tree, "Mixer")
        self.tabs.addTab(self.report_view, "Rapport complet")
        self.render_tree = QTreeWidget()
        self.render_tree.setHeaderLabels(["Rendu", "État", "Durée", "Crête", "Format"])
        self.render_tree.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabs.addTab(self.render_tree, "Son récupéré")
        layout.addWidget(self.tabs, 1)

        bottom = QHBoxLayout()
        self.btn_save = QPushButton("Enregistrer le rapport…")
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self.save_report)
        bottom.addStretch(1)
        bottom.addWidget(self.btn_save)
        layout.addLayout(bottom)

        self.setCentralWidget(root)
        if check_updates:
            self.update_worker = UpdateWorker()
            self.update_worker.finished_check.connect(self.on_update_result)
            self.update_worker.start()

    # -- project selection & analysis ------------------------------------
    def choose_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Sélectionner un projet FL Studio", "", "Projets FL Studio (*.flp)"
        )
        if path:
            self.set_project(Path(path))

    def set_project(self, path: Path) -> None:
        self.project_path = path
        self.path_label.setText(f"{path.name}  —  {path.parent}")
        self.btn_analyze.setEnabled(True)
        self.btn_render.setEnabled(False)
        self.report = None
        self.error.setText("")

    def start_analysis(self) -> None:
        if self.project_path is None or (self.worker and self.worker.isRunning()):
            return
        self.error.setText("")
        self.btn_analyze.setEnabled(False)
        self.btn_select.setEnabled(False)
        self.btn_save.setEnabled(False)
        self.btn_render.setEnabled(False)
        self.worker = InspectWorker(self.project_path)
        self.worker.progress.connect(self.on_progress)
        self.worker.done.connect(self.on_done)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()

    def on_progress(self, index: int, total: int, label: str) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(index)
        self.progress.setFormat(f"Étape {index + 1}/{total}")
        self.status.setText(f"{label}…")

    def on_failed(self, step: str, message: str) -> None:
        self.progress.setValue(0)
        self.progress.setFormat("Échec")
        self.status.setText("")
        self.error.setText(f"L'analyse a échoué à l'étape « {step} » : {message}")
        self.btn_analyze.setEnabled(True)
        self.btn_select.setEnabled(True)

    def on_done(self, report: InspectionReport) -> None:
        self.report = report
        self.progress.setValue(self.progress.maximum())
        self.progress.setFormat("Analyse terminée")
        n_voc = len(report.vocal_sources)
        self.status.setText(
            f"{len(report.sources)} source(s) sonore(s), dont {n_voc} voix détectée(s). "
            f"{len(report.warnings)} avertissement(s). Le projet original n'a pas été modifié."
        )
        self.fill_sources(report)
        self.fill_mixer(report)
        self.report_view.setMarkdown(render_markdown(report))
        self.btn_analyze.setEnabled(True)
        self.btn_select.setEnabled(True)
        self.btn_save.setEnabled(True)
        self.btn_render.setEnabled(True)

    # -- getting the sound out of FL Studio --------------------------------
    def start_render(self) -> None:
        if self.report is None or self.project_path is None:
            return
        if self.render_worker and self.render_worker.isRunning():
            return
        self.error.setText("")
        for b in (self.btn_select, self.btn_analyze, self.btn_render):
            b.setEnabled(False)
        self.render_worker = RenderWorker(self.project_path, self.report,
                                          self.renderer_factory, self.probe)
        self.render_worker.progress.connect(self.on_progress)
        self.render_worker.log.connect(lambda m: self.status.setText(m))
        self.render_worker.done.connect(self.on_render_done)
        self.render_worker.failed.connect(self.on_render_failed)
        self.render_worker.start()

    def _render_buttons(self) -> None:
        for b in (self.btn_select, self.btn_analyze, self.btn_render):
            b.setEnabled(True)

    def on_render_failed(self, step: str, message: str) -> None:
        self.progress.setValue(0)
        self.progress.setFormat("Échec")
        self.error.setText(f"Échec à l'étape « {step} » : {message}")
        self._render_buttons()

    def on_render_done(self, result) -> None:
        self.render_result = result
        self.progress.setValue(self.progress.maximum())
        nt = result.null_test
        if result.ok:
            self.progress.setFormat("Son récupéré")
            self.status.setText(f"{nt.message}. Pistes enregistrées dans {result.folder}")
        else:
            self.progress.setFormat("Son récupéré avec des écarts")
            self.error.setText(nt.message if nt else "Vérification impossible : aucune piste à comparer")
        self.render_tree.clear()
        for j in result.jobs:
            c = j.check
            self.render_tree.addTopLevelItem(QTreeWidgetItem([
                j.job.description,
                {"done": "rendu", "resumed": "réutilisé", "failed": "échec"}.get(j.status, j.status),
                f"{c.duration_s:.1f} s" if c else "—",
                f"{c.peak_db:.1f} dBFS" if c else "—",
                f"{c.sample_rate} Hz {c.subtype}" if c else "—",
            ]))
        self.tabs.setCurrentWidget(self.render_tree)
        self._render_buttons()

    def fill_sources(self, report: InspectionReport) -> None:
        self.sources_tree.clear()
        groups = (
            ("Voix", report.vocal_sources),
            ("Instru et autres sources", [s for s in report.sources if not s.role.is_vocal]),
        )
        for title, items in groups:
            parent = QTreeWidgetItem([f"{title} ({len(items)})"])
            self.sources_tree.addTopLevelItem(parent)
            for s in items:
                effects = ", ".join(
                    f"{fx.plugin} ({CATEGORY_LABELS_FR.get(fx.category, fx.category)})"
                    + ("" if fx.active else " [off]")
                    for fx in s.existing_effects
                ) or "—"
                if s.sample:
                    file_txt = Path(s.sample.stored_path.replace("\\", "/")).name
                    if s.sample.status == "missing":
                        file_txt += " (introuvable)"
                else:
                    file_txt = f"Instrument : {s.plugin}" if s.plugin else "—"
                item = QTreeWidgetItem([
                    s.label, s.role.label, s.role.confidence, s.insert_label or "—", effects, file_txt,
                ])
                item.setToolTip(1, "\n".join(s.role.reasons))
                parent.addChild(item)
            parent.setExpanded(True)

    def fill_mixer(self, report: InspectionReport) -> None:
        self.mixer_tree.clear()
        for ins in report.project.inserts:
            if ins.index not in report.used_inserts and ins.is_default:
                continue
            volume = "?" if ins.volume_raw is None else f"{ins.volume_raw / 12800 * 100:.0f} %"
            fx = ", ".join(s.plugin.label for s in ins.slots) or "—"
            outs = ", ".join("Master" if r.target == 0 else f"Insert {r.target}"
                             for r in ins.routes if r.audible) or "—"
            self.mixer_tree.addTopLevelItem(QTreeWidgetItem([str(ins.index), ins.label, volume, fx, outs]))

    def save_report(self) -> None:
        if self.report is None:
            return
        default = (self.project_path.stem if self.project_path else "rapport") + " - rapport Eden.md"
        path, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer le rapport", default, "Markdown (*.md);;JSON (*.json)"
        )
        if not path:
            return
        text = self.report.to_json() if path.lower().endswith(".json") else render_markdown(self.report)
        try:
            Path(path).write_text(text, encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Eden", f"Impossible d'enregistrer le rapport : {exc}")

    # -- updates ------------------------------------------------------------
    def on_update_result(self, result) -> None:
        if result.status == "downloaded":
            self.banner.setText(f"Mise à jour : {result.message}. Elle sera installée à la fermeture d'Eden.")
            self.banner.show()
        elif result.status == "available_no_installer":
            self.banner.setText(f"Mise à jour : {result.message}")
            self.banner.show()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if self.render_worker and self.render_worker.isRunning():
            QMessageBox.information(self, "Eden", "Un rendu FL Studio est en cours : "
                                    "attendez la fin avant de fermer Eden.")
            event.ignore()
            return
        if self.worker and self.worker.isRunning():
            self.worker.wait(5000)
        if self.update_worker and self.update_worker.isRunning():
            self.update_worker.wait(2000)
        from eden.updater import launch_pending_install

        launch_pending_install()
        super().closeEvent(event)


def run(argv: list[str] | None = None) -> int:
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName("Eden")
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    return app.exec()
