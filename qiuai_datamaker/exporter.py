from __future__ import annotations

import csv
import json
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

from .config import AppConfig
from .constants import EXPORT_ROOT, HERMES_AGENT, OPENCLAW_AGENT
from .i18n import I18n
from .storage import SessionStore


class ExportService:
    def __init__(self, store: SessionStore, i18n: I18n) -> None:
        self.store = store
        self.i18n = i18n

    def export_pass_packages(self, config: AppConfig) -> Path | None:
        export_base = Path(config.export_dir) if config.export_dir else EXPORT_ROOT
        export_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_dir = export_base / f"submission_export_{export_stamp}"

        rows = []
        exported_ids: list[int] = []
        scene_lines: list[str] = []

        for session in self.store.list_unexported_pass_sessions():
            source_dir = Path(session.submission_dir)
            if not source_dir.exists():
                continue

            metadata = self._load_submission_metadata(source_dir, session)
            payload_dir = self._resolve_session_payload_dir(source_dir, metadata)
            if payload_dir is None:
                continue

            agent = metadata["agent"]
            session_id = metadata["session_id"]
            target_dir = export_dir / agent / session_id
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(payload_dir, target_dir, dirs_exist_ok=True)

            row = {
                "record_id": session.id,
                "agent": agent,
                "model": metadata["model"],
                "thinking_effort": metadata["thinking_effort"],
                "scene_key": metadata["scene_key"],
                "scene_name": metadata["scene_name"],
                "session_id": session_id,
                "difficulty": session.difficulty,
                "status": session.status,
                "source_name": session.source_name,
                "submission_dir": session.submission_dir,
            }
            rows.append(row)
            scene_lines.append(
                json.dumps(
                    {"session_id": session_id, "scene": metadata["scene_key"]},
                    ensure_ascii=False,
                )
            )
            exported_ids.append(session.id)

        if not rows:
            return None

        self._write_session_scene_jsonl(export_dir / "session-scene.jsonl", scene_lines)
        self._write_csv(export_dir / "summary.csv", rows)
        self._write_excel(export_dir / "summary.xlsx", rows)
        self._write_validation_report(export_dir / "validation_report.json", rows)
        self.store.mark_exported(exported_ids, export_dir.name)
        return export_dir

    def _load_submission_metadata(self, source_dir: Path, session) -> dict:
        metadata_path = source_dir / "metadata.json"
        if metadata_path.exists():
            with metadata_path.open("r", encoding="utf-8") as handle:
                metadata = json.load(handle)
        else:
            metadata = {}
        return {
            "agent": metadata.get("agent") or session.source_agent,
            "model": metadata.get("model") or session.model_name,
            "thinking_effort": metadata.get("thinking_effort") or session.thinking_effort,
            "scene_key": metadata.get("scene_key") or session.scene_key,
            "scene_name": metadata.get("scene_name") or self.i18n.scene_label(session.scene_key),
            "session_id": metadata.get("session_id") or session.session_id,
            "session_dir": metadata.get("session_dir") or session.session_id,
        }

    def _resolve_session_payload_dir(self, source_dir: Path, metadata: dict) -> Path | None:
        preferred = source_dir / metadata["session_dir"]
        if preferred.exists():
            return preferred

        candidates = [
            path for path in source_dir.iterdir() if path.is_dir() and any(path.glob("*.json"))
        ]
        if len(candidates) == 1:
            return candidates[0]

        nested_match = next(
            (
                path
                for path in source_dir.rglob("*")
                if path.is_dir() and path.name == metadata["session_id"] and any(path.glob("*.json"))
            ),
            None,
        )
        return nested_match

    def _write_session_scene_jsonl(self, path: Path, lines: list[str]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")

    def _write_csv(self, path: Path, rows: list[dict]) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "record_id",
                    "agent",
                    "model",
                    "thinking_effort",
                    "scene_key",
                    "scene_name",
                    "session_id",
                    "difficulty",
                    "status",
                    "source_name",
                    "submission_dir",
                ],
            )
            writer.writeheader()
            writer.writerows(rows)

    def _write_excel(self, path: Path, rows: list[dict]) -> None:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "summary"
        headers = [
            "record_id",
            "agent",
            "model",
            "thinking_effort",
            "scene_key",
            "scene_name",
            "session_id",
            "difficulty",
            "status",
            "source_name",
            "submission_dir",
        ]
        sheet.append(headers)
        for row in rows:
            sheet.append([row.get(header, "") for header in headers])
        workbook.save(path)

    def _write_validation_report(self, path: Path, rows: list[dict]) -> None:
        total = len(rows)
        agent_counts = Counter(row["agent"] for row in rows)
        model_counts = Counter(row["model"] for row in rows)
        effort_counts = Counter(row["thinking_effort"] for row in rows)
        scene_counts = Counter(row["scene_key"] for row in rows)

        report = {
            "total_sessions": total,
            "agent_counts": dict(agent_counts),
            "model_counts": dict(model_counts),
            "thinking_effort_counts": dict(effort_counts),
            "scene_counts": dict(scene_counts),
            "checks": {
                "agent_ratio_openclaw_to_hermes": self._ratio_check(
                    agent_counts.get(OPENCLAW_AGENT, 0),
                    agent_counts.get(HERMES_AGENT, 0),
                ),
                "model_ratio_4_8_to_4_6": self._ratio_check(
                    model_counts.get("claude-opus-4-8", 0),
                    model_counts.get("claude-opus-4-6", 0),
                ),
                "thinking_effort_ratio_xhigh_to_max": self._ratio_check(
                    effort_counts.get("xhigh", 0),
                    effort_counts.get("max", 0),
                ),
                "scene_coverage_count": len(scene_counts),
                "scene_max_min_ratio": self._scene_extreme_ratio(scene_counts),
            },
        }
        with path.open("w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)

    def _ratio_check(self, left: int, right: int) -> dict:
        total = left + right
        return {
            "left": left,
            "right": right,
            "left_share": (left / total) if total else 0,
            "right_share": (right / total) if total else 0,
        }

    def _scene_extreme_ratio(self, scene_counts: Counter) -> float | None:
        positive_counts = [count for count in scene_counts.values() if count > 0]
        if not positive_counts:
            return None
        return max(positive_counts) / min(positive_counts)
