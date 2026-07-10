from __future__ import annotations

import csv
import shutil
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

from .config import AppConfig
from .constants import EXPORT_ROOT, PROCESS_STATUS_PASS
from .i18n import I18n
from .storage import SessionStore


class ExportService:
    def __init__(self, store: SessionStore, i18n: I18n) -> None:
        self.store = store
        self.i18n = i18n

    def export_pass_packages(self, config: AppConfig) -> Path:
        export_base = Path(config.export_dir) if config.export_dir else EXPORT_ROOT
        export_dir = export_base / f"submission_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        packages_dir = export_dir / "packages"
        packages_dir.mkdir(parents=True, exist_ok=True)

        rows = []
        for session in self.store.list_sessions():
            if session.status != PROCESS_STATUS_PASS or not session.submission_dir:
                continue
            source_dir = Path(session.submission_dir)
            if not source_dir.exists():
                continue
            target_dir = packages_dir / source_dir.name
            shutil.copytree(source_dir, target_dir, dirs_exist_ok=True)
            rows.append(
                {
                    "record_id": session.id,
                    "agent": session.source_agent,
                    "model": session.model_name,
                    "scene_key": session.scene_key,
                    "scene_name": self.i18n.scene_label(session.scene_key),
                    "session_id": session.session_id,
                    "difficulty": session.difficulty,
                    "status": session.status,
                    "source_name": session.source_name,
                    "submission_dir": session.submission_dir,
                }
            )

        self._write_csv(export_dir / "summary.csv", rows)
        self._write_excel(export_dir / "summary.xlsx", rows)
        return export_dir

    def _write_csv(self, path: Path, rows: list[dict]) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "record_id",
                    "agent",
                    "model",
                    "scene_key",
                    "scene_name",
                    "session_id",
                    "difficulty",
                    "status",
                    "source_name",
                    "submission_dir",
                ],
            )
            writer.writeheader()
            writer.writerows(rows)

    def _write_excel(self, path: Path, rows: list[dict]) -> None:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "summary"
        headers = [
            "record_id",
            "agent",
            "model",
            "scene_key",
            "scene_name",
            "session_id",
            "difficulty",
            "status",
            "source_name",
            "submission_dir",
        ]
        sheet.append(headers)
        for row in rows:
            sheet.append([row.get(header, "") for header in headers])
        workbook.save(path)
