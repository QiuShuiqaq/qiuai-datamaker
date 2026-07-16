from __future__ import annotations

import unittest
from unittest.mock import patch

from trajectory_scripts import quality_check


def make_call(
    index: int,
    *,
    thinking: bool = True,
    request_messages: list[dict] | None = None,
    response_text: bool = True,
) -> dict:
    content = []
    if thinking:
        content.append(
            {
                "type": "thinking",
                "thinking": f"reasoning {index}",
                "signature": "signature",
            }
        )
    if response_text:
        content.append({"type": "text", "text": f"answer {index}"})
    return {
        "session_id": "session-123",
        "request_id": f"request-{index}",
        "timestamp": f"2026-07-15T10:20:{index:02d}Z",
        "thinking_effort": "xhigh",
        "request": {
            "model": "claude-opus-4-8",
            "system": [{"type": "text", "text": "system"}],
            "thinking": {"type": "adaptive"},
            "tools": [],
            "messages": request_messages
            or [{"role": "user", "content": [{"type": "text", "text": "question"}]}],
        },
        "response": {
            "response_data": {
                "content": content,
                "stop_reason": "end_turn",
            }
        },
    }


class CustomerQualityCheckTests(unittest.TestCase):
    def test_tool_error_detection_matches_customer_script(self) -> None:
        self.assertTrue(
            quality_check.tool_result_is_error({"content": '{"status":"error"}'})
        )
        self.assertTrue(quality_check.tool_result_is_error({"is_error": True}))
        self.assertTrue(quality_check.tool_result_is_error({"is_error": 1}))
        self.assertFalse(
            quality_check.tool_result_is_error(
                {"content": "Exception: validation failed for tool"}
            )
        )
        self.assertFalse(
            quality_check.tool_result_is_error({"content": '{"STATUS":"ERROR"}'})
        )

    def test_rejects_scaffold_pattern_when_only_some_turns_have_thinking(self) -> None:
        calls = [
            make_call(index, thinking=index < 3)
            for index in range(5)
        ]

        with patch.object(quality_check, "load_session_calls", return_value=calls):
            ok, errors, _, stats = quality_check.validate_session(None)

        self.assertFalse(ok)
        self.assertGreater(stats["thinking_density"], 0.5)
        self.assertTrue(any("first assistant turn" in error for error in errors))

    def test_rejects_customer_tool_error_threshold(self) -> None:
        messages = [{"role": "user", "content": [{"type": "text", "text": "question"}]}]
        for index in range(4):
            tool_id = f"tool-{index}"
            messages.extend(
                [
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "tool_use", "id": tool_id, "name": "run", "input": {}}
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": '{"status":"error"}' if index == 0 else "ok",
                            }
                        ],
                    },
                ]
            )
        calls = [make_call(index) for index in range(4)]
        calls.append(make_call(4, request_messages=messages))
        calls[-1]["request"]["tools"] = [
            {"name": "run", "description": "Run", "input_schema": {"type": "object"}}
        ]

        with patch.object(quality_check, "load_session_calls", return_value=calls):
            ok, errors, _, stats = quality_check.validate_session(None)

        self.assertFalse(ok)
        self.assertEqual(stats["tool_error_ratio"], 0.25)
        self.assertTrue(any("tool error ratio" in error for error in errors))

    def test_rejects_missing_final_text(self) -> None:
        calls = [make_call(index) for index in range(5)]
        calls[-1] = make_call(4, response_text=False)

        with patch.object(quality_check, "load_session_calls", return_value=calls):
            ok, errors, _, _ = quality_check.validate_session(None)

        self.assertFalse(ok)
        self.assertTrue(any("does not contain a non-empty text" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
