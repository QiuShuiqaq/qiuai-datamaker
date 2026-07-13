from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class SessionRecord:
    id: int
    source_agent: str
    source_name: str
    source_path: str
    fingerprint: str
    import_method: str
    scene_key: str
    status: str
    model_name: str
    thinking_effort: str
    session_id: str
    difficulty: str
    converted_dir: str
    qc_output_dir: str
    submission_dir: str
    last_error: str
    log_path: str
    source_mtime: float
    metadata_json: str
    created_at: str
    updated_at: str
    exported_at: str = ""
    export_batch: str = ""

    @property
    def updated_at_text(self) -> str:
        if not self.updated_at:
            return ""
        return self.updated_at


@dataclass
class ProcessResult:
    status: str
    session_id: str = ""
    model_name: str = ""
    thinking_effort: str = ""
    difficulty: str = ""
    converted_dir: str = ""
    qc_output_dir: str = ""
    submission_dir: str = ""
    last_error: str = ""
    log_path: str = ""
    metadata: dict[str, Any] | None = None


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
