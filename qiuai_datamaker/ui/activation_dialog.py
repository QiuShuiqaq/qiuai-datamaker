from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..license import get_device_fingerprint, save_activation, validate_activation_data


class ActivationDialog(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.fingerprint = get_device_fingerprint()
        self._build_ui()

    def _build_ui(self) -> None:
        self.setWindowTitle("QiuAi Datamaker Activation")
        self.setModal(True)
        self.resize(640, 240)

        layout = QVBoxLayout(self)

        intro = QLabel("This device needs activation before use.")
        layout.addWidget(intro)

        hint = QLabel("Send the device fingerprint to the admin, then import the activation file.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.fingerprint_edit = QLineEdit(self.fingerprint)
        self.fingerprint_edit.setReadOnly(True)
        layout.addWidget(self.fingerprint_edit)

        self.expires_label = QLabel("Expires At: -")
        layout.addWidget(self.expires_label)

        button_row = QHBoxLayout()
        self.copy_button = QPushButton("Copy Fingerprint")
        self.copy_button.clicked.connect(self.copy_fingerprint)
        self.import_button = QPushButton("Import Activation")
        self.import_button.clicked.connect(self.import_activation)
        self.exit_button = QPushButton("Exit")
        self.exit_button.clicked.connect(self.reject)
        button_row.addWidget(self.copy_button)
        button_row.addWidget(self.import_button)
        button_row.addStretch()
        button_row.addWidget(self.exit_button)
        layout.addLayout(button_row)

        self.status_label = QLabel("Status: not activated")
        layout.addWidget(self.status_label)

    def copy_fingerprint(self) -> None:
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(self.fingerprint)
        self.status_label.setText("Status: fingerprint copied")

    def import_activation(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Activation File",
            str(Path.home()),
            "JSON Files (*.json);;All Files (*.*)",
        )
        if not file_path:
            return

        try:
            with Path(file_path).open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            QMessageBox.critical(self, "Activation Failed", f"Unable to read file.\n{exc}")
            return

        status = validate_activation_data(data, expected_fingerprint=self.fingerprint)
        if not status.valid:
            QMessageBox.critical(self, "Activation Failed", status.message)
            self.status_label.setText(f"Status: {status.message}")
            return

        save_activation(data)
        self.expires_label.setText(f"Expires At: {status.expires_at}")
        self.status_label.setText("Status: activated")
        QMessageBox.information(
            self,
            "Activation Success",
            f"Activation completed.\nExpires At: {status.expires_at}",
        )
        self.accept()
