from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from qiuai_datamaker.group7_validation import (
    LABEL_FIELDS,
    load_normalized_label_payload,
    normalize_label_payload,
    validate_label_payload,
    write_label_payload,
)
from trajectory_scripts.batch_deepseek_simple import normalize_reply


class Group7LabelValidationTests(unittest.TestCase):
    def test_normalize_matches_customer_field_contract(self) -> None:
        payload = normalize_label_payload(
            {"justification": "Multi-step debugging.", "task_difficulty": "HIGH"},
            "session-123",
            "2026-07-15 10:20:30",
            "https://api.deepseek.com",
        )

        self.assertEqual(tuple(payload), LABEL_FIELDS)
        self.assertEqual(
            payload,
            {
                "session_id": "session-123",
                "evaluation_time": "2026-07-15 10:20:30",
                "api_base": "https://api.deepseek.com",
                "justification": "Multi-step debugging.",
                "task_difficulty": "high",
            },
        )

    def test_rejects_legacy_model_field_and_missing_api_base(self) -> None:
        payload = {
            "session_id": "session-123",
            "task_difficulty": "high",
            "justification": "Multi-step debugging.",
            "model": "deepseek/deepseek-v4-pro",
            "evaluation_time": "2026-07-15 10:20:30",
        }

        errors = validate_label_payload(payload, "session-123")

        self.assertTrue(any("api_base" in error for error in errors))
        self.assertTrue(any("model" in error for error in errors))

    def test_rejects_invalid_metadata_types_and_formats(self) -> None:
        payload = {
            "session_id": "session-123",
            "evaluation_time": "2026-7-15 10:20:30",
            "api_base": "api.deepseek.com",
            "justification": ["Multi-step debugging."],
            "task_difficulty": "high",
        }

        errors = validate_label_payload(payload, "session-123")

        self.assertTrue(any("justification: must be a string" in error for error in errors))
        self.assertTrue(any("invalid evaluation_time" in error for error in errors))
        self.assertTrue(any("invalid api_base" in error for error in errors))

    def test_loader_does_not_repair_invalid_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = Path(temp_dir) / "session-123"
            session_dir.mkdir()
            payload = {
                "session_id": "wrong-session",
                "evaluation_time": "2026-07-15 10:20:30",
                "api_base": "https://api.deepseek.com",
                "justification": "Multi-step debugging.",
                "task_difficulty": "high",
            }
            (session_dir / "task_difficulty_justification.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )

            normalized, errors = load_normalized_label_payload(session_dir)

            self.assertEqual(normalized, {})
            self.assertTrue(any("session_id mismatch" in error for error in errors))

    def test_writer_uses_only_the_customer_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = Path(temp_dir) / "session-123"
            session_dir.mkdir()
            payload = {
                "session_id": "session-123",
                "evaluation_time": "2026-07-15 10:20:30",
                "api_base": "https://api.deepseek.com",
                "justification": "Multi-step debugging.",
                "task_difficulty": "high",
            }

            write_label_payload(session_dir, payload)
            written = json.loads(
                (session_dir / "task_difficulty_justification.json").read_text(encoding="utf-8")
            )

            self.assertEqual(tuple(written), LABEL_FIELDS)

    def test_standalone_label_script_matches_customer_contract(self) -> None:
        payload, difficulty = normalize_reply(
            '{"justification":"Multi-step debugging.","task_difficulty":"high"}',
            "session-123",
            "2026-07-15 10:20:30",
            "https://api.deepseek.com",
        )

        self.assertEqual(difficulty, "high")
        self.assertEqual(tuple(payload), LABEL_FIELDS)
        self.assertNotIn("model", payload)


if __name__ == "__main__":
    unittest.main()
