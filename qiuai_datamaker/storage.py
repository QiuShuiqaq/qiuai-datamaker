from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from .constants import DB_PATH
from .models import SessionRecord, now_text


class SessionStore:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_agent TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    source_path TEXT NOT NULL UNIQUE,
                    fingerprint TEXT NOT NULL,
                    import_method TEXT NOT NULL,
                    scene_key TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    model_name TEXT NOT NULL DEFAULT '',
                    thinking_effort TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    difficulty TEXT NOT NULL DEFAULT '',
                    converted_dir TEXT NOT NULL DEFAULT '',
                    qc_output_dir TEXT NOT NULL DEFAULT '',
                    submission_dir TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT '',
                    log_path TEXT NOT NULL DEFAULT '',
                    source_mtime REAL NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    exported_at TEXT NOT NULL DEFAULT '',
                    export_batch TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
            }
            if "exported_at" not in columns:
                conn.execute(
                    "ALTER TABLE sessions ADD COLUMN exported_at TEXT NOT NULL DEFAULT ''"
                )
            if "export_batch" not in columns:
                conn.execute(
                    "ALTER TABLE sessions ADD COLUMN export_batch TEXT NOT NULL DEFAULT ''"
                )

    def upsert_session(
        self,
        *,
        source_agent: str,
        source_name: str,
        source_path: str,
        fingerprint: str,
        import_method: str,
        source_mtime: float,
    ) -> None:
        now = now_text()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    source_agent, source_name, source_path, fingerprint, import_method,
                    status, source_mtime, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'new', ?, ?, ?)
                ON CONFLICT(source_path) DO UPDATE SET
                    source_name=excluded.source_name,
                    fingerprint=excluded.fingerprint,
                    source_path=excluded.source_path,
                    source_mtime=excluded.source_mtime,
                    updated_at=excluded.updated_at
                """,
                (
                    source_agent,
                    source_name,
                    source_path,
                    fingerprint,
                    import_method,
                    source_mtime,
                    now,
                    now,
                ),
            )

    def list_sessions(self) -> list[SessionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        return [SessionRecord(**dict(row)) for row in rows]

    def list_sessions_by_status(self, statuses: Iterable[str]) -> list[SessionRecord]:
        statuses = list(statuses)
        if not statuses:
            return []
        placeholders = ", ".join("?" for _ in statuses)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM sessions
                WHERE status IN ({placeholders})
                ORDER BY updated_at DESC, id DESC
                """,
                statuses,
            ).fetchall()
        return [SessionRecord(**dict(row)) for row in rows]

    def list_unexported_pass_sessions(self) -> list[SessionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM sessions
                WHERE status='pass'
                  AND submission_dir <> ''
                  AND exported_at = ''
                ORDER BY updated_at DESC, id DESC
                """
            ).fetchall()
        return [SessionRecord(**dict(row)) for row in rows]

    def get_sessions_by_ids(self, ids: Iterable[int]) -> list[SessionRecord]:
        ids = list(ids)
        if not ids:
            return []
        placeholders = ", ".join("?" for _ in ids)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM sessions WHERE id IN ({placeholders}) ORDER BY id",
                ids,
            ).fetchall()
        return [SessionRecord(**dict(row)) for row in rows]

    def update_scene(self, session_id: int, scene_key: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET scene_key=?, updated_at=? WHERE id=?",
                (scene_key, now_text(), session_id),
            )

    def bulk_update_scene(self, session_ids: Iterable[int], scene_key: str) -> int:
        session_ids = list(session_ids)
        if not session_ids:
            return 0
        now = now_text()
        with self._connect() as conn:
            conn.executemany(
                "UPDATE sessions SET scene_key=?, updated_at=? WHERE id=?",
                [(scene_key, now, session_id) for session_id in session_ids],
            )
        return len(session_ids)

    def bulk_apply_scene_ready(self, session_ids: Iterable[int], scene_key: str) -> int:
        session_ids = list(session_ids)
        if not session_ids:
            return 0
        now = now_text()
        with self._connect() as conn:
            conn.executemany(
                """
                UPDATE sessions
                SET scene_key=?, status='ready', last_error='',
                    exported_at='', export_batch='', updated_at=?
                WHERE id=?
                """,
                [(scene_key, now, session_id) for session_id in session_ids],
            )
        return len(session_ids)

    def bulk_update_status(
        self,
        session_ids: Iterable[int],
        status: str,
        *,
        clear_error: bool = False,
    ) -> int:
        session_ids = list(session_ids)
        if not session_ids:
            return 0
        now = now_text()
        if clear_error:
            sql = """
                UPDATE sessions
                SET status=?, last_error='', exported_at='', export_batch='', updated_at=?
                WHERE id=?
            """
            params = [(status, now, session_id) for session_id in session_ids]
        else:
            sql = """
                UPDATE sessions
                SET status=?, exported_at='', export_batch='', updated_at=?
                WHERE id=?
            """
            params = [(status, now, session_id) for session_id in session_ids]
        with self._connect() as conn:
            conn.executemany(sql, params)
        return len(session_ids)

    def update_processing_result(
        self,
        session_id: int,
        *,
        status: str,
        model_name: str = "",
        thinking_effort: str = "",
        agent_session_id: str = "",
        difficulty: str = "",
        converted_dir: str = "",
        qc_output_dir: str = "",
        submission_dir: str = "",
        last_error: str = "",
        log_path: str = "",
        metadata: dict | None = None,
    ) -> None:
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET status=?, model_name=?, thinking_effort=?, session_id=?, difficulty=?,
                    converted_dir=?, qc_output_dir=?, submission_dir=?, last_error=?,
                    log_path=?, metadata_json=?, exported_at='', export_batch='',
                    updated_at=?
                WHERE id=?
                """,
                (
                    status,
                    model_name,
                    thinking_effort,
                    agent_session_id,
                    difficulty,
                    converted_dir,
                    qc_output_dir,
                    submission_dir,
                    last_error,
                    log_path,
                    metadata_json,
                    now_text(),
                    session_id,
                ),
            )

    def mark_exported(self, session_ids: Iterable[int], export_batch: str) -> int:
        session_ids = list(session_ids)
        if not session_ids:
            return 0
        exported_at = now_text()
        with self._connect() as conn:
            conn.executemany(
                """
                UPDATE sessions
                SET exported_at=?, export_batch=?, updated_at=?
                WHERE id=?
                """,
                [
                    (exported_at, export_batch, exported_at, session_id)
                    for session_id in session_ids
                ],
            )
        return len(session_ids)

    def clear_export_marks(self, session_ids: Iterable[int]) -> int:
        session_ids = list(session_ids)
        if not session_ids:
            return 0
        now = now_text()
        with self._connect() as conn:
            conn.executemany(
                """
                UPDATE sessions
                SET exported_at='', export_batch='', updated_at=?
                WHERE id=?
                """,
                [(now, session_id) for session_id in session_ids],
            )
        return len(session_ids)

    def summarize(self) -> dict:
        sessions = self.list_sessions()
        summary = {
            "total": len(sessions),
            "pass": 0,
            "fail": 0,
            "error": 0,
            "new": 0,
            "ready": 0,
            "excluded": 0,
            "by_agent": {},
            "by_model": {},
            "by_scene": {},
        }

        for session in sessions:
            summary[session.status] = summary.get(session.status, 0) + 1
            if session.status == "pass":
                summary["by_agent"][session.source_agent] = (
                    summary["by_agent"].get(session.source_agent, 0) + 1
                )
                if session.model_name:
                    summary["by_model"][session.model_name] = (
                        summary["by_model"].get(session.model_name, 0) + 1
                    )
                if session.scene_key:
                    summary["by_scene"][session.scene_key] = (
                        summary["by_scene"].get(session.scene_key, 0) + 1
                    )
        return summary
