from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable

from openai import OpenAI

from .config import AppConfig
from .constants import (
    HERMES_AGENT,
    OPENCLAW_AGENT,
    PROCESS_STATUS_ERROR,
    PROCESS_STATUS_FAIL,
    PROCESS_STATUS_PASS,
    PROCESS_STATUS_PROCESSING,
    SUBMISSION_ROOT,
    WORK_ROOT,
)
from .i18n import I18n
from .logging_service import create_task_logger
from .models import ProcessResult, SessionRecord
from .script_loader import (
    get_convert_hermes_module,
    get_convert_openclaw_module,
    get_label_module,
    get_quality_check_module,
)
from .storage import SessionStore


class PipelineRunner:
    def __init__(self, store: SessionStore, i18n: I18n) -> None:
        self.store = store
        self.i18n = i18n

    def process_sessions(
        self,
        records: list[SessionRecord],
        config: AppConfig,
        progress: Callable[[str], None] | None = None,
    ) -> list[ProcessResult]:
        results: list[ProcessResult] = []
        for record in records:
            results.append(self.process_single_session(record, config, progress))
        return results

    def process_single_session(
        self,
        record: SessionRecord,
        config: AppConfig,
        progress: Callable[[str], None] | None = None,
    ) -> ProcessResult:
        def emit(message: str) -> None:
            if progress:
                progress(message)

        if not record.scene_key:
            result = ProcessResult(
                status=PROCESS_STATUS_ERROR,
                last_error=self.i18n.t("pipeline_scene_required"),
            )
            self._persist_result(record.id, result)
            return result

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        task_name = f"session_{record.id}_{timestamp}"
        task_logger, log_path = create_task_logger(task_name)
        self.store.update_processing_result(
            record.id,
            status=PROCESS_STATUS_PROCESSING,
            log_path=str(log_path),
            last_error="",
        )
        emit(self.i18n.t("pipeline_start", record_id=record.id, source_name=record.source_name))
        task_logger.info("Start processing %s", record.source_path)

        job_root = WORK_ROOT / task_name
        input_dir = job_root / "input"
        converted_dir = job_root / "converted"
        qc_root = job_root / "qc"
        label_root = job_root / "difficulty_labels"
        for path in (input_dir, converted_dir, qc_root, label_root):
            path.mkdir(parents=True, exist_ok=True)

        try:
            raw_file = self._prepare_input(record, input_dir)
            emit(self.i18n.t("pipeline_raw_prepared", record_id=record.id))

            session_dirs = self._run_convert(record, converted_dir, raw_file, task_logger)
            if not session_dirs:
                raise RuntimeError(self.i18n.t("pipeline_conversion_empty"))
            emit(self.i18n.t("pipeline_conversion_complete", record_id=record.id))

            metadata = self._extract_session_metadata(session_dirs[0])
            qc_result, pass_session_dir, qc_output_dir, qc_details = self._run_quality_check(
                session_dirs, qc_root, task_logger
            )
            emit(
                self.i18n.t(
                    "pipeline_qc_complete",
                    record_id=record.id,
                    status=self.i18n.t(f"status.{qc_result}"),
                )
            )

            if qc_result != PROCESS_STATUS_PASS or pass_session_dir is None:
                metadata.update(
                    {
                        "qc_errors": qc_details.get("errors", []),
                        "qc_warnings": qc_details.get("warnings", []),
                        "qc_stats": qc_details.get("stats", {}),
                    }
                )
                result = ProcessResult(
                    status=PROCESS_STATUS_FAIL,
                    session_id=metadata.get("session_id", ""),
                    model_name=metadata.get("model_name", ""),
                    thinking_effort=metadata.get("thinking_effort", ""),
                    converted_dir=str(converted_dir),
                    qc_output_dir=str(qc_output_dir),
                    log_path=str(log_path),
                    last_error=self._summarize_qc_errors(qc_details.get("errors", [])),
                    metadata=metadata,
                )
                self._persist_result(record.id, result)
                return result

            difficulty = self._run_label(
                pass_session_dir, label_root, config, task_logger, emit
            )
            emit(
                self.i18n.t(
                    "pipeline_label_complete",
                    record_id=record.id,
                    difficulty=difficulty or self.i18n.t("pipeline_not_labeled"),
                )
            )

            submission_dir = self._build_submission_package(
                record, metadata, pass_session_dir
            )
            emit(self.i18n.t("pipeline_submission_created", record_id=record.id))

            result = ProcessResult(
                status=PROCESS_STATUS_PASS,
                session_id=metadata.get("session_id", ""),
                model_name=metadata.get("model_name", ""),
                thinking_effort=metadata.get("thinking_effort", ""),
                difficulty=difficulty,
                converted_dir=str(converted_dir),
                qc_output_dir=str(qc_output_dir),
                submission_dir=str(submission_dir),
                log_path=str(log_path),
                metadata=metadata,
            )
            self._persist_result(record.id, result)
            return result

        except Exception as exc:
            task_logger.exception("Processing failed")
            result = ProcessResult(
                status=PROCESS_STATUS_ERROR,
                log_path=str(log_path),
                last_error=str(exc),
            )
            self._persist_result(record.id, result)
            emit(self.i18n.t("pipeline_processing_failed", record_id=record.id, error=str(exc)))
            return result

    def _prepare_input(self, record: SessionRecord, input_dir: Path) -> Path:
        source_path = Path(record.source_path)
        target_path = input_dir / source_path.name
        shutil.copy2(source_path, target_path)
        return target_path

    def _run_convert(
        self,
        record: SessionRecord,
        converted_dir: Path,
        raw_file: Path,
        task_logger,
    ) -> list[Path]:
        if record.source_agent == OPENCLAW_AGENT:
            module = get_convert_openclaw_module()
            task_logger.info("Using OpenClaw converter")
            module.convert_file(str(raw_file), str(converted_dir), module.get_system_prompt())
        elif record.source_agent == HERMES_AGENT:
            module = get_convert_hermes_module()
            task_logger.info("Using Hermes converter")
            module.convert_file(str(raw_file), str(converted_dir), None)
        else:
            raise RuntimeError(self.i18n.t("pipeline_unsupported_agent", agent=record.source_agent))

        return sorted(
            path
            for path in converted_dir.iterdir()
            if path.is_dir() and any(path.glob("*.json"))
        )

    def _extract_session_metadata(self, session_dir: Path) -> dict:
        first_call = next(iter(sorted(session_dir.glob("*.json"))), None)
        if first_call is None:
            return {}
        with first_call.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return {
            "session_id": data.get("session_id", session_dir.name),
            "model_name": data.get("request", {}).get("model", ""),
            "thinking_effort": data.get("thinking_effort", ""),
        }

    def _run_quality_check(
        self,
        session_dirs: list[Path],
        qc_root: Path,
        task_logger,
    ) -> tuple[str, Path | None, Path, dict]:
        module = get_quality_check_module()
        pass_dir = qc_root / "pass"
        fail_dir = qc_root / "fail"
        report_dir = qc_root / "report"
        for path in (pass_dir, fail_dir, report_dir):
            path.mkdir(parents=True, exist_ok=True)

        status = PROCESS_STATUS_FAIL
        pass_session_dir: Path | None = None
        results = []
        chosen_result: dict | None = None
        for session_dir in session_dirs:
            task_logger.info("Quality check session dir: %s", session_dir)
            result = module.process_session_dir(session_dir, pass_dir, fail_dir)
            results.append(result)
            if result["status"] == "pass":
                status = PROCESS_STATUS_PASS
                pass_session_dir = pass_dir / result["session_id"]
                chosen_result = result
            elif chosen_result is None:
                chosen_result = result

        report_path = report_dir / "summary.json"
        with report_path.open("w", encoding="utf-8") as handle:
            json.dump(results, handle, ensure_ascii=False, indent=2)
        return status, pass_session_dir, qc_root, (chosen_result or {})

    def _summarize_qc_errors(self, errors: list[str]) -> str:
        if not errors:
            return self.i18n.t("pipeline_qc_failed")
        summary = " | ".join(error.strip() for error in errors[:2] if error.strip())
        if len(errors) > 2:
            summary = f"{summary} ..."
        return summary or self.i18n.t("pipeline_qc_failed")

    def _run_label(
        self,
        pass_session_dir: Path,
        label_root: Path,
        config: AppConfig,
        task_logger,
        emit: Callable[[str], None],
    ) -> str:
        if not config.deepseek_api_key:
            task_logger.info("Skip label: no API key configured")
            return ""

        module = get_label_module()
        last_call = module.find_last_call_file(pass_session_dir)
        if last_call is None:
            raise RuntimeError(self.i18n.t("pipeline_label_call_missing"))

        with last_call.open("r", encoding="utf-8") as handle:
            content = handle.read().strip()

        prompt = module.PROMPT_TEMPLATE.format(trajectory_content=content)
        client = OpenAI(
            api_key=config.deepseek_api_key,
            base_url=config.deepseek_api_base,
        )
        emit(self.i18n.t("pipeline_label_calling"))
        response = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        reply = response.choices[0].message.content.strip()
        task_logger.info("Label response: %s", reply)

        parsed = json.loads(reply)
        difficulty = parsed.get("difficulty") or parsed.get("task_difficulty", "")
        label_root.mkdir(parents=True, exist_ok=True)
        label_file = label_root / f"{pass_session_dir.name}.json"
        with label_file.open("w", encoding="utf-8") as handle:
            json.dump(
                {
                    "session_id": pass_session_dir.name,
                    "difficulty": difficulty,
                    "justification": parsed.get("justification", ""),
                    "evaluation_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "api_base": config.deepseek_api_base,
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )

        justification_file = pass_session_dir / "task_difficulty_justification.json"
        with justification_file.open("w", encoding="utf-8") as handle:
            json.dump(parsed, handle, ensure_ascii=False, indent=2)
        return difficulty

    def _build_submission_package(
        self,
        record: SessionRecord,
        metadata: dict,
        pass_session_dir: Path,
    ) -> Path:
        scene_name = self.i18n.scene_label(record.scene_key)
        model_name = metadata.get("model_name") or "unknown_model"
        session_id = metadata.get("session_id") or pass_session_dir.name

        package_root = SUBMISSION_ROOT / f"{record.id}_{session_id}"
        if package_root.exists():
            shutil.rmtree(package_root)

        target_dir = package_root / session_id
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(pass_session_dir, target_dir)

        metadata_file = package_root / "metadata.json"
        with metadata_file.open("w", encoding="utf-8") as handle:
            json.dump(
                {
                    "record_id": record.id,
                    "agent": record.source_agent,
                    "model": model_name,
                    "thinking_effort": metadata.get("thinking_effort", ""),
                    "scene_key": record.scene_key,
                    "scene_name": scene_name,
                    "session_id": session_id,
                    "source_name": record.source_name,
                    "session_dir": target_dir.name,
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )
        return package_root

    def _persist_result(self, record_id: int, result: ProcessResult) -> None:
        self.store.update_processing_result(
            record_id,
            status=result.status,
            model_name=result.model_name,
            thinking_effort=result.thinking_effort,
            agent_session_id=result.session_id,
            difficulty=result.difficulty,
            converted_dir=result.converted_dir,
            qc_output_dir=result.qc_output_dir,
            submission_dir=result.submission_dir,
            last_error=result.last_error,
            log_path=result.log_path,
            metadata=result.metadata or {},
        )
