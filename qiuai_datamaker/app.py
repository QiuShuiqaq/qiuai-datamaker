from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from .bootstrap import ensure_runtime_dirs
from .config import ConfigStore
from .i18n import I18n
from .license import get_saved_activation_status
from .logging_service import setup_logging
from .pipeline import PipelineRunner
from .runtime import get_icon_path
from .scanner import SourceScanner
from .storage import SessionStore
from .ui.activation_dialog import ActivationDialog
from .ui.main_window import MainWindow


def main() -> int:
    ensure_runtime_dirs()
    logger = setup_logging()
    logger.info("Application starting")

    app = QApplication(sys.argv)
    icon_path = get_icon_path()
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    activation_status = get_saved_activation_status()
    if not activation_status.valid:
        logger.info("Activation required: %s", activation_status.message)
        dialog = ActivationDialog()
        if dialog.exec() != ActivationDialog.Accepted:
            logger.info("Application exited before activation")
            return 0

    store = SessionStore()
    config_store = ConfigStore()
    config = config_store.load()
    i18n = I18n(config.language)
    scanner = SourceScanner(store)
    pipeline = PipelineRunner(store, i18n)

    window = MainWindow(
        store=store,
        config_store=config_store,
        scanner=scanner,
        pipeline=pipeline,
        i18n=i18n,
    )
    logger.info("Main window created")
    window.show()
    window.setWindowState((window.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
    window.raise_()
    window.activateWindow()
    logger.info("Main window shown and activated")
    if "--startup-check" in sys.argv:
        QMessageBox.information(
            window,
            i18n.t("startup_check_title"),
            i18n.t("startup_check_text"),
        )
    return app.exec()
