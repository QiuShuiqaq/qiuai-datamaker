from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from qiuai_datamaker.config import AppConfig
from qiuai_datamaker.exporter import ExportService


class FakeStore:
    def __init__(self, sessions: list[SimpleNamespace]) -> None:
        self.sessions = sessions
        self.marked: tuple[list[int], str] | None = None

    def list_unexported_pass_sessions(self) -> list[SimpleNamespace]:
        return self.sessions

    def mark_exported(self, session_ids: list[int], export_batch: str) -> None:
        self.marked = (session_ids, export_batch)


class FakeI18n:
    def scene_label(self, scene_key: str) -> str:
        return scene_key


class ExportServiceTests(unittest.TestCase):
    def _write_valid_package(
        self,
        package_dir: Path,
        session_id: str,
        *,
        raw_snapshot: bytes | None = None,
    ) -> None:
        payload_dir = package_dir / session_id
        payload_dir.mkdir(parents=True)
        (payload_dir / "0000.json").write_text("{}", encoding="utf-8")
        (payload_dir / "task_difficulty_justification.json").write_text(
            json.dumps(
                {
                    "session_id": session_id,
                    "evaluation_time": "2026-07-15 10:20:30",
                    "api_base": "https://api.deepseek.com",
                    "justification": "Multi-step debugging.",
                    "task_difficulty": "high",
                }
            ),
            encoding="utf-8",
        )
        metadata = {
            "agent": "openclaw",
            "session_id": session_id,
            "session_dir": session_id,
        }
        if raw_snapshot is not None:
            snapshot_path = package_dir / "_raw_source" / "source.jsonl"
            snapshot_path.parent.mkdir()
            snapshot_path.write_bytes(raw_snapshot)
            metadata["raw_source_file"] = "_raw_source/source.jsonl"
        (package_dir / "metadata.json").write_text(
            json.dumps(metadata), encoding="utf-8"
        )

    def _session(
        self,
        record_id: int,
        package_dir: Path,
        source_path: Path,
        session_id: str,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            id=record_id,
            submission_dir=str(package_dir),
            source_agent="openclaw",
            session_id=session_id,
            scene_key="development",
            source_name="source.jsonl",
            source_path=str(source_path),
            model_name="claude-opus-4-8",
            difficulty="high",
            import_method="watch",
            fingerprint=f"fingerprint-{record_id}",
            source_mtime=123.5,
        )

    def test_mismatched_metadata_session_id_is_not_exported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_dir = root / "package"
            payload_dir = package_dir / "actual-session"
            payload_dir.mkdir(parents=True)
            (package_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "agent": "openclaw",
                        "session_id": "different-session",
                        "session_dir": "different-session",
                    }
                ),
                encoding="utf-8",
            )
            (payload_dir / "task_difficulty_justification.json").write_text(
                json.dumps(
                    {
                        "session_id": "actual-session",
                        "evaluation_time": "2026-07-15 10:20:30",
                        "api_base": "https://api.deepseek.com",
                        "justification": "Multi-step debugging.",
                        "task_difficulty": "high",
                    }
                ),
                encoding="utf-8",
            )
            session = SimpleNamespace(
                id=1,
                submission_dir=str(package_dir),
                source_agent="openclaw",
                session_id="actual-session",
                scene_key="coding",
                source_name="source.jsonl",
                source_path=str(root / "source.jsonl"),
            )
            store = FakeStore([session])
            service = ExportService(store, FakeI18n())

            exported = service.export_pass_packages(
                AppConfig(export_dir=str(root / "exports"))
            )

            self.assertIsNone(exported)
            self.assertIsNone(store.marked)
            self.assertFalse((root / "exports").exists())

    def test_export_creates_separate_traceable_raw_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_dir = root / "package"
            source_path = root / "source.jsonl"
            source_path.write_bytes(b"changed after processing\n")
            self._write_valid_package(
                package_dir,
                "session-123",
                raw_snapshot=b"exact processed source\n",
            )
            session = self._session(1, package_dir, source_path, "session-123")
            store = FakeStore([session])

            result = ExportService(store, FakeI18n()).export_pass_packages(
                AppConfig(export_dir=str(root / "exports"))
            )

            self.assertIsNotNone(result)
            backup_file = (
                result.backup_dir
                / "files"
                / "openclaw"
                / "1_session-123"
                / "source.jsonl"
            )
            self.assertEqual(backup_file.read_bytes(), b"exact processed source\n")
            self.assertFalse((result.delivery_dir / "_raw_source").exists())
            self.assertFalse((result.delivery_dir / "manifest.json").exists())

            manifest = json.loads(
                (result.backup_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["schema_version"], 1)
            self.assertIn("app_version", manifest)
            self.assertEqual(manifest["record_count"], 1)
            record = manifest["records"][0]
            self.assertEqual(record["backup_source"], "processing_snapshot")
            self.assertEqual(
                record["sha256"], hashlib.sha256(b"exact processed source\n").hexdigest()
            )
            self.assertEqual(store.marked[0], [1])

    def test_legacy_package_uses_existing_source_path_as_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_dir = root / "package"
            source_path = root / "source.jsonl"
            source_path.write_bytes(b"legacy source\n")
            self._write_valid_package(package_dir, "session-123")
            session = self._session(1, package_dir, source_path, "session-123")
            store = FakeStore([session])

            result = ExportService(store, FakeI18n()).export_pass_packages(
                AppConfig(export_dir=str(root / "exports"))
            )

            manifest = json.loads(
                (result.backup_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["records"][0]["backup_source"], "source_path_fallback")

    def test_missing_raw_source_is_not_exported_or_marked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_dir = root / "package"
            self._write_valid_package(package_dir, "session-123")
            session = self._session(
                1, package_dir, root / "missing.jsonl", "session-123"
            )
            store = FakeStore([session])

            result = ExportService(store, FakeI18n()).export_pass_packages(
                AppConfig(export_dir=str(root / "exports"))
            )

            self.assertIsNone(result)
            self.assertIsNone(store.marked)
            self.assertFalse((root / "exports").exists())

    def test_same_named_sources_are_backed_up_without_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sessions = []
            for record_id in (1, 2):
                session_id = f"session-{record_id}"
                package_dir = root / f"package-{record_id}"
                source_path = root / f"source-{record_id}" / "source.jsonl"
                source_path.parent.mkdir()
                source_path.write_bytes(f"source {record_id}\n".encode())
                self._write_valid_package(package_dir, session_id)
                sessions.append(
                    self._session(record_id, package_dir, source_path, session_id)
                )
            store = FakeStore(sessions)

            result = ExportService(store, FakeI18n()).export_pass_packages(
                AppConfig(export_dir=str(root / "exports"))
            )

            manifest = json.loads(
                (result.backup_dir / "manifest.json").read_text(encoding="utf-8")
            )
            backup_files = [record["backup_file"] for record in manifest["records"]]
            self.assertEqual(len(backup_files), 2)
            self.assertEqual(len(set(backup_files)), 2)


if __name__ == "__main__":
    unittest.main()
