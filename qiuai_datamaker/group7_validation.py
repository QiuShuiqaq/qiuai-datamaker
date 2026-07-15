from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


ALLOWED_TASK_DIFFICULTIES = frozenset({"low", "medium", "high", "xhigh", "expert"})
LABEL_JSON_NAME = "task_difficulty_justification.json"
LABEL_JSONL_NAME = "task_difficulty_justification.jsonl"
LABEL_FIELDS = (
    "session_id",
    "evaluation_time",
    "api_base",
    "justification",
    "task_difficulty",
)


def normalize_label_payload(
    source: dict,
    session_id: str,
    evaluation_time: str,
    api_base: str,
) -> dict[str, str]:
    difficulty = str(source.get("task_difficulty") or source.get("difficulty") or "").strip().lower()
    justification = str(source.get("justification") or "").strip()
    return {
        "session_id": session_id,
        "evaluation_time": evaluation_time,
        "api_base": api_base,
        "justification": justification,
        "task_difficulty": difficulty,
    }


def validate_label_payload(payload: dict, session_id: str) -> list[str]:
    errors: list[str] = []
    actual_fields = set(payload)
    expected_fields = set(LABEL_FIELDS)
    missing_fields = expected_fields - actual_fields
    unexpected_fields = actual_fields - expected_fields
    if missing_fields:
        errors.append(f"missing fields: {', '.join(sorted(missing_fields))}")
    if unexpected_fields:
        errors.append(f"unexpected fields: {', '.join(sorted(unexpected_fields))}")

    for field in LABEL_FIELDS:
        if field in payload and not isinstance(payload[field], str):
            errors.append(f"invalid {field}: must be a string")

    payload_session_id = str(payload.get("session_id") or "").strip()
    if payload_session_id != session_id:
        errors.append(
            f"session_id mismatch: expected '{session_id}', got '{payload_session_id or '<empty>'}'"
        )

    difficulty = str(payload.get("task_difficulty") or "").strip().lower()
    if not difficulty:
        errors.append("missing task_difficulty")
    elif difficulty not in ALLOWED_TASK_DIFFICULTIES:
        allowed = ", ".join(sorted(ALLOWED_TASK_DIFFICULTIES))
        errors.append(f"invalid task_difficulty '{difficulty}' (allowed: {allowed})")

    if not str(payload.get("justification") or "").strip():
        errors.append("missing justification")

    evaluation_time = str(payload.get("evaluation_time") or "").strip()
    if not evaluation_time:
        errors.append("missing evaluation_time")
    else:
        try:
            parsed_evaluation_time = datetime.strptime(evaluation_time, "%Y-%m-%d %H:%M:%S")
            if parsed_evaluation_time.strftime("%Y-%m-%d %H:%M:%S") != evaluation_time:
                raise ValueError
        except ValueError:
            errors.append("invalid evaluation_time: expected YYYY-MM-DD HH:MM:SS")

    api_base = str(payload.get("api_base") or "").strip()
    if not api_base:
        errors.append("missing api_base")
    else:
        parsed_api_base = urlparse(api_base)
        if parsed_api_base.scheme not in {"http", "https"} or not parsed_api_base.netloc:
            errors.append("invalid api_base: expected an HTTP(S) URL")

    return errors


def load_normalized_label_payload(session_dir: Path) -> tuple[dict[str, str], list[str]]:
    json_path = session_dir / LABEL_JSON_NAME
    if not json_path.exists():
        return {}, [f"missing {LABEL_JSON_NAME}"]

    try:
        with json_path.open("r", encoding="utf-8") as handle:
            source = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {}, [f"invalid {LABEL_JSON_NAME}: {exc}"]

    if not isinstance(source, dict):
        return {}, [f"invalid {LABEL_JSON_NAME}: root must be a JSON object"]

    errors = validate_label_payload(source, session_dir.name)
    if errors:
        return {}, errors

    normalized = normalize_label_payload(
        source,
        str(source["session_id"]).strip(),
        str(source["evaluation_time"]).strip(),
        str(source["api_base"]).strip(),
    )
    return normalized, []


def write_label_payload(session_dir: Path, payload: dict[str, str]) -> None:
    errors = validate_label_payload(payload, session_dir.name)
    if errors:
        raise ValueError(f"invalid difficulty label: {'; '.join(errors)}")

    json_path = session_dir / LABEL_JSON_NAME
    jsonl_path = session_dir / LABEL_JSONL_NAME
    with json_path.open("w", encoding="utf-8") as handle:
        ordered_payload = {field: payload[field] for field in LABEL_FIELDS}
        json.dump(ordered_payload, handle, ensure_ascii=False, indent=4)
    if jsonl_path.exists():
        jsonl_path.unlink()
