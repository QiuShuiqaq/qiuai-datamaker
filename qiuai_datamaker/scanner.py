from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Iterable

from .config import AppConfig
from .constants import HERMES_AGENT, OPENCLAW_AGENT, RAW_IMPORT_ROOT
from .storage import SessionStore


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    raw = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _is_openclaw_candidate(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != ".jsonl":
        return False
    if path.name.endswith(".trajectory.jsonl"):
        return False
    return True


def _is_hermes_candidate(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != ".json":
        return False
    if path.name.startswith("."):
        return False
    if path.name == "task_difficulty_justification.json":
        return False
    if path.stem[:4].isdigit() and "_" in path.stem:
        return False
    return True


class SourceScanner:
    def __init__(self, store: SessionStore) -> None:
        self.store = store

    def scan_configured_sources(self, config: AppConfig) -> dict[str, int]:
        counts = {"openclaw": 0, "hermes": 0}
        counts["openclaw"] = self._scan_agent_dir(
            OPENCLAW_AGENT, Path(config.openclaw_source_dir) if config.openclaw_source_dir else None
        )
        counts["hermes"] = self._scan_agent_dir(
            HERMES_AGENT, Path(config.hermes_source_dir) if config.hermes_source_dir else None
        )
        return counts

    def _scan_agent_dir(self, agent: str, source_dir: Path | None) -> int:
        if source_dir is None or not source_dir.exists():
            return 0

        matcher = _is_openclaw_candidate if agent == OPENCLAW_AGENT else _is_hermes_candidate
        count = 0
        for file_path in source_dir.rglob("*"):
            if not matcher(file_path):
                continue
            self.store.upsert_session(
                source_agent=agent,
                source_name=file_path.name,
                source_path=str(file_path),
                fingerprint=_fingerprint(file_path),
                import_method="watch",
                source_mtime=file_path.stat().st_mtime,
            )
            count += 1
        return count

    def import_files(self, agent: str, paths: Iterable[Path]) -> int:
        target_root = RAW_IMPORT_ROOT / agent
        target_root.mkdir(parents=True, exist_ok=True)
        count = 0
        for src_path in paths:
            target_path = self._copy_manual_file(src_path, target_root)
            self.store.upsert_session(
                source_agent=agent,
                source_name=target_path.name,
                source_path=str(target_path),
                fingerprint=_fingerprint(target_path),
                import_method="manual",
                source_mtime=target_path.stat().st_mtime,
            )
            count += 1
        return count

    def _copy_manual_file(self, src_path: Path, target_root: Path) -> Path:
        candidate = target_root / src_path.name
        if not candidate.exists():
            shutil.copy2(src_path, candidate)
            return candidate

        stem = src_path.stem
        suffix = src_path.suffix
        idx = 1
        while True:
            candidate = target_root / f"{stem}_{idx}{suffix}"
            if not candidate.exists():
                shutil.copy2(src_path, candidate)
                return candidate
            idx += 1
