from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig, ConfigStore
from ..constants import (
    AGENT_LABELS,
    APP_NAME,
    DATA_ROOT,
    HERMES_AGENT,
    OPENCLAW_AGENT,
    SCENES,
    TARGET_AGENT_RATIO,
    TARGET_MODEL_RATIO,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
)
from ..exporter import ExportService
from ..i18n import I18n
from ..pipeline import PipelineRunner
from ..runtime import get_icon_path
from ..scanner import SourceScanner
from ..storage import SessionStore
from ..worker import WorkerThread


class DropArea(QLabel):
    files_dropped = Signal(list)

    def __init__(self, i18n: I18n) -> None:
        super().__init__()
        self.i18n = i18n
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.setStyleSheet(
            "QLabel { border: 2px dashed #999; padding: 16px; color: #555; }"
        )
        self.refresh_text()

    def refresh_text(self) -> None:
        self.setText(self.i18n.t("drop_area"))

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        files = []
        for url in event.mimeData().urls():
            if url.isLocalFile():
                files.append(url.toLocalFile())
        if files:
            self.files_dropped.emit(files)
            event.acceptProposedAction()
        else:
            event.ignore()


class MainWindow(QMainWindow):
    def __init__(
        self,
        *,
        store: SessionStore,
        config_store: ConfigStore,
        scanner: SourceScanner,
        pipeline: PipelineRunner,
        i18n: I18n,
    ) -> None:
        super().__init__()
        self.store = store
        self.config_store = config_store
        self.scanner = scanner
        self.pipeline = pipeline
        self.i18n = i18n
        self.exporter = ExportService(store, i18n)
        self.config = self.config_store.load()
        self.active_thread: WorkerThread | None = None

        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        icon_path = get_icon_path()
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self._build_ui()
        self._load_config_into_ui()
        self.apply_language()
        self.refresh_all()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        top_bar = QHBoxLayout()
        top_bar.addStretch()
        self.language_button = QPushButton()
        self.language_button.clicked.connect(self.toggle_language)
        top_bar.addWidget(self.language_button)
        layout.addLayout(top_bar)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.guidance_tab = self._build_guidance_tab()
        self.batch_tab = self._build_batch_tab()
        self.quota_tab = self._build_quota_tab()
        self.export_tab = self._build_export_tab()

        self.tabs.addTab(self.guidance_tab, "")
        self.tabs.addTab(self.batch_tab, "")
        self.tabs.addTab(self.quota_tab, "")
        self.tabs.addTab(self.export_tab, "")

        self.status_bar = self.statusBar()
        self._build_actions()

    def _build_actions(self) -> None:
        self.open_data_action = QAction("", self)
        self.open_data_action.triggered.connect(lambda: self._open_path(DATA_ROOT))
        self.menuBar().addAction(self.open_data_action)

    def _build_guidance_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.path_group = QGroupBox()
        form = QFormLayout(self.path_group)

        self.openclaw_dir_edit = QLineEdit()
        self.hermes_dir_edit = QLineEdit()
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_base_edit = QLineEdit()
        self.export_dir_edit = QLineEdit()

        self.label_openclaw_dir = QLabel()
        self.openclaw_browse = QPushButton()
        form.addRow(
            self.label_openclaw_dir,
            self._with_browse_button(self.openclaw_dir_edit, self.openclaw_browse),
        )

        self.label_hermes_dir = QLabel()
        self.hermes_browse = QPushButton()
        form.addRow(
            self.label_hermes_dir,
            self._with_browse_button(self.hermes_dir_edit, self.hermes_browse),
        )

        self.label_api_key = QLabel()
        form.addRow(self.label_api_key, self.api_key_edit)

        self.label_api_base = QLabel()
        form.addRow(self.label_api_base, self.api_base_edit)

        self.label_export_dir = QLabel()
        self.export_dir_browse = QPushButton()
        form.addRow(
            self.label_export_dir,
            self._with_browse_button(self.export_dir_edit, self.export_dir_browse),
        )
        layout.addWidget(self.path_group)

        button_row = QHBoxLayout()
        self.save_config_button = QPushButton()
        self.save_config_button.clicked.connect(self.save_config)
        self.scan_now_button = QPushButton()
        self.scan_now_button.clicked.connect(self.scan_sources)
        button_row.addWidget(self.save_config_button)
        button_row.addWidget(self.scan_now_button)
        button_row.addStretch()
        layout.addLayout(button_row)

        self.scene_group = QGroupBox()
        scene_layout = QVBoxLayout(self.scene_group)
        self.scene_list = QListWidget()
        scene_layout.addWidget(self.scene_list)
        layout.addWidget(self.scene_group, stretch=1)

        self.tips_group = QGroupBox()
        tips_layout = QVBoxLayout(self.tips_group)
        self.tips_text = QPlainTextEdit()
        self.tips_text.setReadOnly(True)
        tips_layout.addWidget(self.tips_text)
        layout.addWidget(self.tips_group, stretch=1)
        return widget

    def _build_batch_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        toolbar = QHBoxLayout()
        self.label_manual_import_agent = QLabel()
        self.import_agent_combo = QComboBox()
        self.import_agent_combo.addItem("OpenClaw", OPENCLAW_AGENT)
        self.import_agent_combo.addItem("Hermes", HERMES_AGENT)

        self.label_scene = QLabel()
        self.scene_combo = QComboBox()

        self.scan_button = QPushButton()
        self.scan_button.clicked.connect(self.scan_sources)
        self.import_button = QPushButton()
        self.import_button.clicked.connect(self.import_files)
        self.scene_button = QPushButton()
        self.scene_button.clicked.connect(self.apply_scene_to_selected)
        self.process_button = QPushButton()
        self.process_button.clicked.connect(self.process_selected)
        self.retry_button = QPushButton()
        self.retry_button.clicked.connect(self.retry_failed)

        toolbar.addWidget(self.label_manual_import_agent)
        toolbar.addWidget(self.import_agent_combo)
        toolbar.addWidget(self.import_button)
        toolbar.addSpacing(12)
        toolbar.addWidget(self.label_scene)
        toolbar.addWidget(self.scene_combo)
        toolbar.addWidget(self.scene_button)
        toolbar.addSpacing(12)
        toolbar.addWidget(self.scan_button)
        toolbar.addWidget(self.process_button)
        toolbar.addWidget(self.retry_button)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.drop_area = DropArea(self.i18n)
        self.drop_area.files_dropped.connect(self.handle_dropped_files)
        layout.addWidget(self.drop_area)

        self.session_table = QTableWidget(0, 9)
        self.session_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.session_table.setSelectionMode(QAbstractItemView.MultiSelection)
        self.session_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.session_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.session_table, stretch=1)

        self.batch_log = QPlainTextEdit()
        self.batch_log.setReadOnly(True)
        layout.addWidget(self.batch_log, stretch=1)
        return widget

    def _build_quota_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.summary_group = QGroupBox()
        summary_layout = QGridLayout(self.summary_group)
        self.summary_total_label = QLabel()
        self.summary_total = QLabel("-")
        self.summary_pass_label = QLabel()
        self.summary_pass = QLabel("-")
        self.summary_fail_label = QLabel()
        self.summary_fail = QLabel("-")
        self.summary_error_label = QLabel()
        self.summary_error = QLabel("-")
        summary_layout.addWidget(self.summary_total_label, 0, 0)
        summary_layout.addWidget(self.summary_total, 0, 1)
        summary_layout.addWidget(self.summary_pass_label, 0, 2)
        summary_layout.addWidget(self.summary_pass, 0, 3)
        summary_layout.addWidget(self.summary_fail_label, 1, 0)
        summary_layout.addWidget(self.summary_fail, 1, 1)
        summary_layout.addWidget(self.summary_error_label, 1, 2)
        summary_layout.addWidget(self.summary_error, 1, 3)
        layout.addWidget(self.summary_group)

        self.agent_stats = QPlainTextEdit()
        self.agent_stats.setReadOnly(True)
        self.model_stats = QPlainTextEdit()
        self.model_stats.setReadOnly(True)
        self.scene_stats = QPlainTextEdit()
        self.scene_stats.setReadOnly(True)

        self.agent_group = self._wrap_text_box("", self.agent_stats)
        self.model_group = self._wrap_text_box("", self.model_stats)
        self.scene_stats_group = self._wrap_text_box("", self.scene_stats)

        layout.addWidget(self.agent_group)
        layout.addWidget(self.model_group)
        layout.addWidget(self.scene_stats_group, stretch=1)
        return widget

    def _build_export_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.export_group = QGroupBox()
        form = QFormLayout(self.export_group)
        self.export_target_edit = QLineEdit()
        self.label_export_target = QLabel()
        self.export_target_browse = QPushButton()
        form.addRow(
            self.label_export_target,
            self._with_browse_button(self.export_target_edit, self.export_target_browse),
        )
        layout.addWidget(self.export_group)

        button_row = QHBoxLayout()
        self.export_button = QPushButton()
        self.export_button.clicked.connect(self.export_packages)
        self.open_export_button = QPushButton()
        self.open_export_button.clicked.connect(
            lambda: self._open_path(Path(self.export_target_edit.text() or "."))
        )
        button_row.addWidget(self.export_button)
        button_row.addWidget(self.open_export_button)
        button_row.addStretch()
        layout.addLayout(button_row)

        self.export_log = QPlainTextEdit()
        self.export_log.setReadOnly(True)
        layout.addWidget(self.export_log, stretch=1)
        return widget

    def _with_browse_button(self, line_edit: QLineEdit, button: QPushButton) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        button.clicked.connect(lambda: self.browse_directory(line_edit))
        layout.addWidget(line_edit)
        layout.addWidget(button)
        return widget

    def _wrap_text_box(self, title: str, text_box: QPlainTextEdit) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.addWidget(text_box)
        return group

    def _load_config_into_ui(self) -> None:
        self.openclaw_dir_edit.setText(self.config.openclaw_source_dir)
        self.hermes_dir_edit.setText(self.config.hermes_source_dir)
        self.api_key_edit.setText(self.config.deepseek_api_key)
        self.api_base_edit.setText(self.config.deepseek_api_base)
        self.export_dir_edit.setText(self.config.export_dir)
        self.export_target_edit.setText(self.config.export_dir)

    def apply_language(self) -> None:
        self.setWindowTitle(self.i18n.t("app_name"))
        self.language_button.setText(self.i18n.t("button_language"))
        self.open_data_action.setText(self.i18n.t("menu_open_data"))
        self.tabs.setTabText(0, self.i18n.t("tab_guidance"))
        self.tabs.setTabText(1, self.i18n.t("tab_batch"))
        self.tabs.setTabText(2, self.i18n.t("tab_quota"))
        self.tabs.setTabText(3, self.i18n.t("tab_export"))

        self.path_group.setTitle(self.i18n.t("group_base_config"))
        self.label_openclaw_dir.setText(self.i18n.t("label_openclaw_dir"))
        self.label_hermes_dir.setText(self.i18n.t("label_hermes_dir"))
        self.label_api_key.setText(self.i18n.t("label_api_key"))
        self.label_api_base.setText(self.i18n.t("label_api_base"))
        self.label_export_dir.setText(self.i18n.t("label_export_dir"))
        for button in (
            self.openclaw_browse,
            self.hermes_browse,
            self.export_dir_browse,
            self.export_target_browse,
        ):
            button.setText(self.i18n.t("button_browse"))
        self.save_config_button.setText(self.i18n.t("button_save_config"))
        self.scan_now_button.setText(self.i18n.t("button_scan_sources"))

        self.scene_group.setTitle(self.i18n.t("group_required_scenes"))
        self.scene_list.clear()
        for key, _ in SCENES:
            QListWidgetItem(self.i18n.scene_label(key), self.scene_list)

        self.tips_group.setTitle(self.i18n.t("group_workflow_tips"))
        self.tips_text.setPlainText(self.i18n.t("tips_workflow"))

        self.label_manual_import_agent.setText(self.i18n.t("label_manual_import_agent"))
        self.label_scene.setText(self.i18n.t("label_scene"))
        self.import_button.setText(self.i18n.t("button_import_files"))
        self.scene_button.setText(self.i18n.t("button_apply_scene"))
        self.process_button.setText(self.i18n.t("button_process_selected"))
        self.retry_button.setText(self.i18n.t("button_retry_failed"))
        self.scan_button.setText(self.i18n.t("button_scan"))
        self.drop_area.refresh_text()
        self.scene_combo.blockSignals(True)
        self.scene_combo.clear()
        self.scene_combo.addItem(self.i18n.t("select_scene"), "")
        for key, _ in SCENES:
            self.scene_combo.addItem(self.i18n.scene_label(key), key)
        self.scene_combo.blockSignals(False)
        self.session_table.setHorizontalHeaderLabels(
            [
                self.i18n.t("table_id"),
                self.i18n.t("table_status"),
                self.i18n.t("table_agent"),
                self.i18n.t("table_source"),
                self.i18n.t("table_scene"),
                self.i18n.t("table_model"),
                self.i18n.t("table_difficulty"),
                self.i18n.t("table_updated"),
                self.i18n.t("table_error"),
            ]
        )

        self.summary_group.setTitle(self.i18n.t("group_summary"))
        self.summary_total_label.setText(self.i18n.t("label_total"))
        self.summary_pass_label.setText(self.i18n.t("label_pass"))
        self.summary_fail_label.setText(self.i18n.t("label_fail"))
        self.summary_error_label.setText(self.i18n.t("label_error"))
        self.agent_group.setTitle(self.i18n.t("group_agent_quota"))
        self.model_group.setTitle(self.i18n.t("group_model_quota"))
        self.scene_stats_group.setTitle(self.i18n.t("group_scene_coverage"))

        self.export_group.setTitle(self.i18n.t("group_export"))
        self.label_export_target.setText(self.i18n.t("label_export_target"))
        self.export_button.setText(self.i18n.t("button_export_all"))
        self.open_export_button.setText(self.i18n.t("button_open_export"))

        self.refresh_all()

    def toggle_language(self) -> None:
        self.i18n.toggle_language()
        self.config.language = self.i18n.language
        self.config_store.save(self.config)
        self.apply_language()
        self.status_bar.showMessage(self.i18n.t("status_language_changed"), 3000)

    def save_config(self) -> None:
        export_dir = self.export_target_edit.text().strip() or self.export_dir_edit.text().strip()
        self.config = AppConfig(
            openclaw_source_dir=self.openclaw_dir_edit.text().strip(),
            hermes_source_dir=self.hermes_dir_edit.text().strip(),
            deepseek_api_key=self.api_key_edit.text().strip(),
            deepseek_api_base=self.api_base_edit.text().strip() or "https://api.deepseek.com",
            export_dir=export_dir,
            language=self.i18n.language,
        )
        self.config_store.save(self.config)
        self.export_dir_edit.setText(export_dir)
        self.export_target_edit.setText(self.config.export_dir)
        self.status_bar.showMessage(self.i18n.t("config_saved"), 3000)

    def browse_directory(self, target_edit: QLineEdit) -> None:
        directory = QFileDialog.getExistingDirectory(self, self.i18n.t("msg_select_directory"))
        if directory:
            target_edit.setText(directory)

    def refresh_all(self) -> None:
        self.refresh_sessions()
        self.refresh_quota()

    def refresh_sessions(self) -> None:
        sessions = self.store.list_sessions()
        self.session_table.setRowCount(len(sessions))
        for row, session in enumerate(sessions):
            values = [
                str(session.id),
                self.i18n.t(f"status.{session.status}"),
                AGENT_LABELS.get(session.source_agent, session.source_agent),
                session.source_name,
                self.i18n.scene_label(session.scene_key) if session.scene_key else "",
                session.model_name,
                session.difficulty,
                session.updated_at,
                session.last_error,
            ]
            for col, value in enumerate(values):
                self.session_table.setItem(row, col, QTableWidgetItem(value))
        self.session_table.resizeColumnsToContents()

    def refresh_quota(self) -> None:
        summary = self.store.summarize()
        self.summary_total.setText(str(summary["total"]))
        self.summary_pass.setText(str(summary.get("pass", 0)))
        self.summary_fail.setText(str(summary.get("fail", 0)))
        self.summary_error.setText(str(summary.get("error", 0)))

        agent_lines = []
        total_agents = max(sum(summary["by_agent"].values()), 1)
        for agent, target in TARGET_AGENT_RATIO.items():
            count = summary["by_agent"].get(agent, 0)
            ratio = count / total_agents
            agent_lines.append(
                self.i18n.t(
                    "summary_agent_line",
                    agent=AGENT_LABELS[agent],
                    count=count,
                    ratio=ratio,
                    target=target,
                )
            )
        self.agent_stats.setPlainText("\n".join(agent_lines))

        model_lines = []
        total_models = max(sum(summary["by_model"].values()), 1)
        for model, target in TARGET_MODEL_RATIO.items():
            count = summary["by_model"].get(model, 0)
            ratio = count / total_models
            model_lines.append(
                self.i18n.t(
                    "summary_model_line",
                    model=model,
                    count=count,
                    ratio=ratio,
                    target=target,
                )
            )
        self.model_stats.setPlainText("\n".join(model_lines))

        scene_lines = []
        scene_counts = summary["by_scene"]
        values = []
        for key, _ in SCENES:
            count = scene_counts.get(key, 0)
            values.append(count)
            scene_lines.append(
                self.i18n.t(
                    "summary_scene_line",
                    scene=self.i18n.scene_label(key),
                    count=count,
                )
            )
        non_zero = [value for value in values if value > 0]
        if non_zero:
            scene_lines.append(
                self.i18n.t(
                    "summary_scene_coverage",
                    covered=len(non_zero),
                    max_count=max(non_zero),
                    min_count=min(non_zero),
                )
            )
        else:
            scene_lines.append(self.i18n.t("summary_scene_empty"))
        self.scene_stats.setPlainText("\n".join(scene_lines))

    def _selected_ids(self) -> list[int]:
        selected_rows = sorted({index.row() for index in self.session_table.selectedIndexes()})
        ids = []
        for row in selected_rows:
            item = self.session_table.item(row, 0)
            if item:
                ids.append(int(item.text()))
        return ids

    def apply_scene_to_selected(self) -> None:
        scene_key = self.scene_combo.currentData()
        if not scene_key:
            QMessageBox.warning(
                self,
                self.i18n.t("msg_missing_scene_title"),
                self.i18n.t("msg_missing_scene_text"),
            )
            return
        ids = self._selected_ids()
        if not ids:
            QMessageBox.warning(
                self,
                self.i18n.t("msg_no_selection_title"),
                self.i18n.t("msg_no_selection_text"),
            )
            return
        for session_id in ids:
            self.store.update_scene(session_id, scene_key)
        self.refresh_all()
        self.status_bar.showMessage(
            self.i18n.t("status_scene_applied", count=len(ids)),
            3000,
        )

    def scan_sources(self) -> None:
        self.save_config()
        self.batch_log.appendPlainText(self.i18n.t("scan_start"))
        self._run_worker(
            lambda progress: self.scanner.scan_configured_sources(self.config),
            self._after_scan,
        )

    def _after_scan(self, result) -> None:
        self.batch_log.appendPlainText(self.i18n.t("scan_complete", result=result))
        self.refresh_all()

    def import_files(self) -> None:
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            self.i18n.t("msg_select_log_files"),
            "",
            "JSON Files (*.json *.jsonl);;All Files (*.*)",
        )
        if not file_paths:
            return
        self._import_paths(file_paths)

    def handle_dropped_files(self, file_paths: list[str]) -> None:
        self._import_paths(file_paths)

    def _import_paths(self, file_paths: list[str]) -> None:
        agent = self.import_agent_combo.currentData()
        count = self.scanner.import_files(agent, [Path(path) for path in file_paths])
        self.batch_log.appendPlainText(self.i18n.t("imported_files", count=count))
        self.refresh_all()

    def process_selected(self) -> None:
        ids = self._selected_ids()
        if not ids:
            QMessageBox.warning(
                self,
                self.i18n.t("msg_no_selection_title"),
                self.i18n.t("msg_no_selection_text"),
            )
            return
        records = self.store.get_sessions_by_ids(ids)
        self.batch_log.appendPlainText(self.i18n.t("process_start", count=len(records)))
        self._run_worker(
            lambda progress: self.pipeline.process_sessions(records, self.config, progress),
            self._after_process,
        )

    def retry_failed(self) -> None:
        records = [
            session
            for session in self.store.list_sessions()
            if session.status in ("fail", "error")
        ]
        if not records:
            QMessageBox.information(
                self,
                self.i18n.t("msg_no_failed_title"),
                self.i18n.t("msg_no_failed_text"),
            )
            return
        self.batch_log.appendPlainText(self.i18n.t("retry_start", count=len(records)))
        self._run_worker(
            lambda progress: self.pipeline.process_sessions(records, self.config, progress),
            self._after_process,
        )

    def _after_process(self, result) -> None:
        if isinstance(result, list):
            pass_count = sum(1 for item in result if getattr(item, "status", "") == "pass")
            self.batch_log.appendPlainText(
                self.i18n.t("process_complete", pass_count=pass_count, count=len(result))
            )
        else:
            self.batch_log.appendPlainText(self.i18n.t("process_complete_simple"))
        self.refresh_all()

    def export_packages(self) -> None:
        self.save_config()
        self._run_worker(
            lambda progress: self.exporter.export_pass_packages(self.config),
            self._after_export,
        )

    def _after_export(self, export_dir) -> None:
        export_text = self.i18n.t("export_complete", path=export_dir)
        self.export_log.appendPlainText(export_text)
        self.status_bar.showMessage(
            self.i18n.t("status_export_complete", path=export_dir),
            5000,
        )

    def _run_worker(self, fn, on_complete) -> None:
        if self.active_thread and self.active_thread.isRunning():
            QMessageBox.warning(
                self,
                self.i18n.t("msg_busy_title"),
                self.i18n.t("msg_busy_text"),
            )
            return
        self.active_thread = WorkerThread(fn)
        self.active_thread.progress.connect(self._append_progress)
        self.active_thread.completed.connect(on_complete)
        self.active_thread.completed.connect(lambda _: self._thread_done())
        self.active_thread.failed.connect(self._thread_failed)
        self.active_thread.failed.connect(lambda _: self._thread_done())
        self.active_thread.start()

    def _append_progress(self, message: str) -> None:
        self.batch_log.appendPlainText(message)
        self.export_log.appendPlainText(message)

    def _thread_failed(self, error: str) -> None:
        QMessageBox.critical(
            self,
            self.i18n.t("msg_task_failed_title"),
            error,
        )
        self.batch_log.appendPlainText(self.i18n.t("task_failed", error=error))

    def _thread_done(self) -> None:
        self.refresh_all()
        self.active_thread = None

    def _open_path(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(path))
