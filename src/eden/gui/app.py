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


class UpdateWorker(QThread):
    finished_check = Signal(object)

    def run(self) -> None:
        from eden.updater import check_and_download

        self.finished_check.emit(check_and_download())


class MainWindow(QMainWindow):
    def __init__(self, check_updates: bool = True) -> None:
        super().__init__()
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
        row.addWidget(self.btn_select)
        row.addWidget(self.btn_analyze)
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
        self.error.setText("")

    def start_analysis(self) -> None:
        if self.project_path is None or (self.worker and self.worker.isRunning()):
            return
        self.error.setText("")
        self.btn_analyze.setEnabled(False)
        self.btn_select.setEnabled(False)
        self.btn_save.setEnabled(False)
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
