from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from qiuai_datamaker.config import AppConfig
from qiuai_datamaker.pipeline import PipelineRunner


class FakeI18n:
    def scene_label(self, scene_key: str) -> str:
        return scene_key


class PipelineSourceBackupTests(unittest.TestCase):
    def test_submission_package_keeps_the_exact_processed_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            submission_root = root / "submissions"
            pass_session_dir = root / "pass" / "session-123"
            pass_session_dir.mkdir(parents=True)
            (pass_session_dir / "0000.json").write_text("{}", encoding="utf-8")
            raw_file = root / "work" / "source.jsonl"
            raw_file.parent.mkdir()
            raw_file.write_bytes(b"exact processed source\n")
            record = SimpleNamespace(
                id=7,
                source_agent="openclaw",
                source_name="source.jsonl",
                source_path=r"D:\external\source.jsonl",
                fingerprint="source-fingerprint",
                source_mtime=123.5,
                import_method="watch",
                scene_key="development",
            )
            runner = PipelineRunner(store=None, i18n=FakeI18n())

            with patch("qiuai_datamaker.pipeline.SUBMISSION_ROOT", submission_root):
                package_root = runner._build_submission_package(
                    record,
                    {
                        "session_id": "session-123",
                        "model_name": "claude-opus-4-8",
                        "thinking_effort": "high",
                    },
                    pass_session_dir,
                    raw_file,
                    AppConfig(submitter="tester"),
                )

            snapshot = package_root / "_raw_source" / "source.jsonl"
            metadata = json.loads(
                (package_root / "metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(snapshot.read_bytes(), b"exact processed source\n")
            self.assertEqual(metadata["raw_source_file"], "_raw_source/source.jsonl")
            self.assertEqual(metadata["original_source_path"], record.source_path)
            self.assertEqual(metadata["source_fingerprint"], "source-fingerprint")


if __name__ == "__main__":
    unittest.main()
