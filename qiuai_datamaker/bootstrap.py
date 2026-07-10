from __future__ import annotations

from .constants import (
    DATA_ROOT,
    EXPORT_ROOT,
    LOG_ROOT,
    RAW_IMPORT_ROOT,
    SUBMISSION_ROOT,
    TASK_LOG_ROOT,
    WORK_ROOT,
)


def ensure_runtime_dirs() -> None:
    for path in (
        DATA_ROOT,
        LOG_ROOT,
        TASK_LOG_ROOT,
        WORK_ROOT,
        RAW_IMPORT_ROOT,
        SUBMISSION_ROOT,
        EXPORT_ROOT,
    ):
        path.mkdir(parents=True, exist_ok=True)
