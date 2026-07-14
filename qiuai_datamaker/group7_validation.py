from __future__ import annotations

import json
from datetime import datetime
from json import JSONDecoder
from pathlib import Path


ALLOWED_TASK_DIFFICULTIES = frozenset({"low", "medium", "high", "xhigh", "expert"})
LABEL_MODEL = "deepseek/deepseek-v4-pro"
LABEL_JSON_NAME = "task_difficulty_justification.json"
LABEL_JSONL_NAME = "task_difficulty_justification.jsonl"


def decode_first_json_object(text: str) -> dict:
    stripped = text.strip()
    if not stripped:
        return {}
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        decoder = JSONDecoder()
        parsed, _ = decoder.raw_decode(stripped)
        return parsed if isinstance(parsed, dict) else {}


def normalize_label_payload(
    source: dict,
    session_id: str,
    evaluation_time: str,
) -> dict[str, str]:
    difficulty = str(source.get("task_difficulty") or source.get("difficulty") or "").strip().lower()
    justification = str(source.get("justification") or "").strip()
    model = str(source.get("model") or LABEL_MODEL).strip() or LABEL_MODEL
    timestamp = str(source.get("evaluation_time") or evaluation_time).strip() or evaluation_time
    return {
        "session_id": session_id,
        "task_difficulty": difficulty,
        "justification": justification,
        "model": model,
        "evaluation_time": timestamp,
    }


def validate_label_payload(payload: dict, session_id: str) -> list[str]:
    errors: list[str] = []
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

    return errors


def load_normalized_label_payload(session_dir: Path) -> tuple[dict[str, str], list[str]]:
    json_path = session_dir / LABEL_JSON_NAME
    jsonl_path = session_dir / LABEL_JSONL_NAME

    source: dict = {}
    timestamp_source: Path | None = None
    if json_path.exists():
        with json_path.open("r", encoding="utf-8") as handle:
            source = json.load(handle)
        timestamp_source = json_path
    elif jsonl_path.exists():
        source = decode_first_json_object(jsonl_path.read_text(encoding="utf-8"))
        timestamp_source = jsonl_path

    evaluation_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if timestamp_source is not None:
        evaluation_time = datetime.fromtimestamp(timestamp_source.stat().st_mtime).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    normalized = normalize_label_payload(source, session_dir.name, evaluation_time)
    return normalized, validate_label_payload(normalized, session_dir.name)


def write_label_payload(session_dir: Path, payload: dict[str, str]) -> None:
    json_path = session_dir / LABEL_JSON_NAME
    jsonl_path = session_dir / LABEL_JSONL_NAME
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    if jsonl_path.exists():
        jsonl_path.unlink()
