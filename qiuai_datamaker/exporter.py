from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path, PureWindowsPath

from openpyxl import Workbook

from .config import AppConfig
from .constants import EXPORT_ROOT, HERMES_AGENT
from .i18n import I18n
from .storage import SessionStore


DELIVERY_XLSX_NAME = "\u8d28\u68c0\u63d0\u4ea4\u8bb0\u5f55_v2.xlsx"
DELIVERY_SHEET_NAME = "\u8d28\u68c0\u63d0\u4ea4\u8bb0\u5f55"
DELIVERY_SUBMITTER = "Claude\u672c\u673a\u81ea\u8dd1"
DELIVERY_HEADERS = [
    "\u5206\u7ec4",
    "\u63d0\u4ea4\u8005",
    "sessionId",
    "\u5bf9\u8bdd\u573a\u666f",
]


class ExportService:
    def __init__(self, store: SessionStore, i18n: I18n) -> None:
        self.store = store
        self.i18n = i18n

    def export_pass_packages(self, config: AppConfig) -> Path | None:
        export_base = Path(config.export_dir) if config.export_dir else EXPORT_ROOT
        export_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_dir = export_base / f"submission_export_{export_stamp}"

        rows: list[dict] = []
        exported_ids: list[int] = []

        for session in self.store.list_unexported_pass_sessions():
            source_dir = Path(session.submission_dir)
            if not source_dir.exists():
                continue

            metadata = self._load_submission_metadata(source_dir, session)
            payload_dir = self._resolve_session_payload_dir(source_dir, metadata)
            if payload_dir is None:
                continue

            agent_dir_name = self._export_agent_dir_name(metadata["agent"])
            session_id = metadata["session_id"]
            target_dir = export_dir / agent_dir_name / session_id
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(payload_dir, target_dir, dirs_exist_ok=True)

            rows.append(
                {
                    "agent": metadata["agent"],
                    "export_agent": agent_dir_name,
                    "scene_name": metadata["scene_name"],
                    "session_id": session_id,
                    "submitter": metadata["submitter"],
                    "source_name": session.source_name,
                    "source_path": session.source_path,
                }
            )
            exported_ids.append(session.id)

        if not rows:
            return None

        delivery_rows = self._build_delivery_rows(rows)
        self._write_delivery_excel(export_dir / DELIVERY_XLSX_NAME, delivery_rows)
        self.store.mark_exported(exported_ids, export_dir.name)
        return export_dir

    def _load_submission_metadata(self, source_dir: Path, session) -> dict:
        metadata_path = source_dir / "metadata.json"
        metadata = {}
        if metadata_path.exists():
            with metadata_path.open("r", encoding="utf-8") as handle:
                metadata = json.load(handle)
        return {
            "agent": metadata.get("agent") or session.source_agent,
            "scene_name": metadata.get("scene_name")
            or self.i18n.scene_label(session.scene_key),
            "session_id": metadata.get("session_id") or session.session_id,
            "session_dir": metadata.get("session_dir") or session.session_id,
            "submitter": metadata.get("submitter")
            or self._extract_submitter_name(session.source_path),
        }

    def _resolve_session_payload_dir(self, source_dir: Path, metadata: dict) -> Path | None:
        preferred = source_dir / metadata["session_dir"]
        if preferred.exists():
            return preferred

        candidates = [
            path for path in source_dir.iterdir() if path.is_dir() and any(path.glob("*.json"))
        ]
        if len(candidates) == 1:
            return candidates[0]

        nested_match = next(
            (
                path
                for path in source_dir.rglob("*")
                if path.is_dir()
                and path.name == metadata["session_id"]
                and any(path.glob("*.json"))
            ),
            None,
        )
        return nested_match

    def _export_agent_dir_name(self, agent: str) -> str:
        if agent == HERMES_AGENT:
            return "Hermes"
        return agent

    def _write_delivery_excel(self, path: Path, rows: list[dict]) -> None:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = DELIVERY_SHEET_NAME
        sheet.append(DELIVERY_HEADERS)
        for row in rows:
            sheet.append([row.get(header, "") for header in DELIVERY_HEADERS])
        workbook.save(path)

    def _build_delivery_rows(self, rows: list[dict]) -> list[dict]:
        delivery_rows = []
        for row in rows:
            delivery_rows.append(
                {
                    "\u5206\u7ec4": row.get("export_agent", row.get("agent", "")),
                    "\u63d0\u4ea4\u8005": row.get("submitter", "") or DELIVERY_SUBMITTER,
                    "sessionId": row.get("session_id", ""),
                    "\u5bf9\u8bdd\u573a\u666f": row.get("scene_name", ""),
                }
            )
        delivery_rows.sort(
            key=lambda item: (
                str(item.get("sessionId", "")),
                str(item.get("\u5206\u7ec4", "")),
            )
        )
        return delivery_rows

    def _extract_submitter_name(self, source_path: str) -> str:
        patterns = (
            re.compile(r"^\d{8}[-_](.+?)[-_]output\d+$", re.IGNORECASE),
            re.compile(r"^\d{8}[-_](.+?)_output\d+$", re.IGNORECASE),
        )
        for part in reversed(self._source_path_parts(source_path)):
            for pattern in patterns:
                match = pattern.match(part)
                if match:
                    return match.group(1).strip()
        return ""

    def _source_path_parts(self, source_path: str) -> list[str]:
        text = str(source_path).strip()
        if not text:
            return []
        try:
            return [part for part in PureWindowsPath(text).parts if part]
        except Exception:
            return [part for part in text.replace("/", "\\").split("\\") if part]
