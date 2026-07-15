from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
