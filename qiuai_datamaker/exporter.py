from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

from . import __version__
from .config import AppConfig
from .constants import EXPORT_ROOT, HERMES_AGENT
from .group7_validation import load_normalized_label_payload, write_label_payload
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
RAW_BACKUP_MANIFEST_NAME = "manifest.json"
RAW_BACKUP_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ExportResult:
    delivery_dir: Path
    backup_dir: Path
    exported_count: int
    skipped_count: int


class ExportService:
    def __init__(self, store: SessionStore, i18n: I18n) -> None:
        self.store = store
        self.i18n = i18n

    def export_pass_packages(self, config: AppConfig) -> ExportResult | None:
        export_base = Path(config.export_dir) if config.export_dir else EXPORT_ROOT
        export_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_dir = export_base / f"submission_export_{export_stamp}"
        backup_dir = export_base / f"raw_source_backup_{export_stamp}"

        rows: list[dict] = []
        backup_records: list[dict] = []
        exported_ids: list[int] = []
        sessions = self.store.list_unexported_pass_sessions()

        for session in sessions:
            source_dir = Path(session.submission_dir)
            if not source_dir.exists():
                continue

            metadata = self._load_submission_metadata(source_dir, session)
            payload_dir = self._resolve_session_payload_dir(source_dir, metadata)
            if payload_dir is None:
                continue
            normalized_label, label_errors = load_normalized_label_payload(payload_dir)
            if label_errors:
                continue

            agent_dir_name = self._export_agent_dir_name(metadata["agent"])
            session_id = metadata["session_id"]
            if normalized_label["session_id"] != session_id:
                continue
            raw_source = self._resolve_raw_source(source_dir, metadata, session)
            if raw_source is None:
                continue
            raw_source_path, backup_source = raw_source

            backup_record = self._backup_raw_source(
                backup_dir,
                raw_source_path,
                backup_source,
                metadata,
                session,
            )
            target_dir = export_dir / agent_dir_name / session_id
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(payload_dir, target_dir, dirs_exist_ok=True)
            write_label_payload(target_dir, normalized_label)

            rows.append(
                {
                    "agent": metadata["agent"],
                    "export_agent": agent_dir_name,
                    "scene_name": metadata["scene_name"],
                    "session_id": session_id,
                    "submitter": config.submitter.strip() or metadata.get("submitter", ""),
                    "source_name": session.source_name,
                    "source_path": session.source_path,
                }
            )
            backup_records.append(backup_record)
            exported_ids.append(session.id)

        if not rows:
            return None

        delivery_rows = self._build_delivery_rows(rows)
        self._write_delivery_excel(export_dir / DELIVERY_XLSX_NAME, delivery_rows)
        self._write_backup_manifest(backup_dir, export_dir, backup_records)
        self.store.mark_exported(exported_ids, export_dir.name)
        return ExportResult(
            delivery_dir=export_dir,
            backup_dir=backup_dir,
            exported_count=len(exported_ids),
            skipped_count=len(sessions) - len(exported_ids),
        )

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
            "submitter": metadata.get("submitter", ""),
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

    def _resolve_raw_source(
        self,
        package_dir: Path,
        metadata: dict,
        session,
    ) -> tuple[Path, str] | None:
        raw_source_file = str(metadata.get("raw_source_file") or "").strip()
        if raw_source_file:
            package_root = package_dir.resolve()
            snapshot = (package_dir / raw_source_file).resolve()
            if snapshot.is_relative_to(package_root) and snapshot.is_file():
                return snapshot, "processing_snapshot"

        legacy_snapshot = package_dir / "_raw_source" / Path(session.source_name).name
        if legacy_snapshot.is_file():
            return legacy_snapshot, "processing_snapshot"

        original_source = Path(session.source_path)
        if original_source.is_file():
            return original_source, "source_path_fallback"
        return None

    def _backup_raw_source(
        self,
        backup_dir: Path,
        raw_source: Path,
        backup_source: str,
        metadata: dict,
        session,
    ) -> dict:
        agent_name = self._export_agent_dir_name(metadata["agent"])
        session_id = metadata["session_id"]
        relative_path = (
            Path("files")
            / agent_name
            / f"{session.id}_{session_id}"
            / raw_source.name
        )
        target_path = backup_dir / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(raw_source, target_path)

        return {
            "record_id": session.id,
            "session_id": session_id,
            "agent": metadata["agent"],
            "model": getattr(session, "model_name", ""),
            "scene_key": getattr(session, "scene_key", ""),
            "difficulty": getattr(session, "difficulty", ""),
            "source_name": session.source_name,
            "original_source_path": metadata.get("original_source_path")
            or session.source_path,
            "import_method": getattr(session, "import_method", ""),
            "source_fingerprint": getattr(session, "fingerprint", ""),
            "source_mtime": getattr(session, "source_mtime", 0),
            "backup_source": backup_source,
            "backup_file": relative_path.as_posix(),
            "size_bytes": target_path.stat().st_size,
            "sha256": self._sha256_file(target_path),
        }

    def _write_backup_manifest(
        self,
        backup_dir: Path,
        delivery_dir: Path,
        records: list[dict],
    ) -> None:
        records.sort(key=lambda item: (str(item["session_id"]), int(item["record_id"])))
        manifest = {
            "schema_version": RAW_BACKUP_SCHEMA_VERSION,
            "app_version": __version__,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "delivery_directory": delivery_dir.name,
            "record_count": len(records),
            "records": records,
        }
        manifest_path = backup_dir / RAW_BACKUP_MANIFEST_NAME
        with manifest_path.open("w", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)

    def _sha256_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

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
