import argparse
import csv
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")


DEFAULT_AFTER_TIME = "2026-07-06"
ALLOWED_MODELS = {"claude-opus-4-6", "claude-opus-4-8"}
ALLOWED_EFFORTS = {"high", "xhigh", "max"}
ALLOWED_STOP_REASONS = {"end_turn", "tool_use", "max_tokens", "stop_sequence"}
SPECIAL_KEYWORDS = [
    "HEARTBEAT_OK",
    "NO_REPLY",
    "heartbeat poll",
    "[OpenClaw heartbeat poll]",
]
ERROR_SIGNAL_KEYWORDS = ['"status": "error"', '"status":"error"']


def load_session_calls(session_dir: Path) -> list[dict]:
    calls = []
    for json_file in sorted(session_dir.glob("*.json")):
        if json_file.name == "task_difficulty_justification.json":
            continue
        with json_file.open("r", encoding="utf-8") as handle:
            calls.append(json.load(handle))
    return calls


def text_blocks(content) -> list[str]:
    if not isinstance(content, list):
        return []
    return [
        block.get("text", "")
        for block in content
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
    ]


def has_non_empty_text(content) -> bool:
    return any(text.strip() for text in text_blocks(content))


def thinking_blocks(content) -> list[dict]:
    if not isinstance(content, list):
        return []
    return [
        block
        for block in content
        if isinstance(block, dict) and block.get("type") == "thinking"
    ]


def tool_result_blocks(messages: list[dict]) -> list[dict]:
    results = []
    for message in messages:
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                results.append(block)
    return results


def tool_result_is_error(block: dict) -> bool:
    if block.get("is_error"):
        return True
    content = block.get("content")
    if isinstance(content, str):
        return any(keyword in content for keyword in ERROR_SIGNAL_KEYWORDS)
    return False


def normalize_timestamp(value: str | None) -> str:
    if not value:
        return ""
    if value.endswith("Z"):
        return value
    if value.endswith("+00:00"):
        return value.replace("+00:00", "Z")
    return f"{value}Z"


def latest_timestamp(calls: list[dict]) -> str:
    timestamps = [
        normalize_timestamp(call.get("timestamp"))
        for call in calls
        if call.get("timestamp")
    ]
    return max(timestamps) if timestamps else ""


def validate_tool_schema(call_index: int, tools, errors: list[str]) -> set[str]:
    if not isinstance(tools, list):
        errors.append(f"Call {call_index}: request.tools is not a list")
        return set()

    schema_tool_names = set()
    for tool in tools:
        if not isinstance(tool, dict):
            errors.append(f"Call {call_index}: request.tools contains a non-object tool")
            continue
        if not all(key in tool for key in ("name", "description", "input_schema")):
            errors.append(
                f"Call {call_index}: tool definition is missing name/description/input_schema"
            )
            continue
        name = tool.get("name")
        if name:
            schema_tool_names.add(name)
    return schema_tool_names


def validate_assistant_content_blocks(
    call_index: int,
    blocks: list[dict],
    schema_tool_names: set[str],
    errors: list[str],
    assistant_tool_ids: set[str],
) -> None:
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "thinking":
            if not str(block.get("thinking", "")).strip():
                errors.append(f"Call {call_index}: thinking block is empty")
            if not str(block.get("signature", "")).strip():
                errors.append(f"Call {call_index}: thinking block is missing signature")
        elif block_type == "tool_use":
            if not all(key in block for key in ("id", "name", "input")):
                errors.append(f"Call {call_index}: tool_use is missing id/name/input")
                continue
            if not isinstance(block.get("input"), dict):
                errors.append(f"Call {call_index}: tool_use.input is not an object")
            if block.get("name") not in schema_tool_names:
                errors.append(
                    f"Call {call_index}: tool_use '{block.get('name')}' is not defined in request.tools"
                )
            if block.get("id"):
                assistant_tool_ids.add(block["id"])


def validate_session(session_dir: Path) -> tuple[bool, list[str], list[str], dict]:
    calls = load_session_calls(session_dir)
    if not calls:
        return False, ["No valid call files found in the session directory"], [], {}

    errors: list[str] = []
    warnings: list[str] = []
    stats: dict[str, float | int | str] = {}

    session_ids = {call.get("session_id") for call in calls}
    if len(session_ids) > 1:
        errors.append(f"Multiple session_id values found: {sorted(session_ids)}")

    request_ids = [call.get("request_id") for call in calls]
    if len(request_ids) != len(set(request_ids)):
        errors.append("Duplicate request_id values found in the session")

    model_names = [call.get("request", {}).get("model", "") for call in calls]
    if len(set(model_names)) > 1:
        errors.append("request.model is inconsistent within the same session")
    for model_name in model_names:
        if model_name not in ALLOWED_MODELS:
            errors.append(
                f"Model '{model_name}' is not allowed (allowed: {sorted(ALLOWED_MODELS)})"
            )

    garbled_count = 0
    for call_index, call in enumerate(calls):
        if call.get("is_garbled") is True:
            garbled_count += 1

        thinking_effort = call.get("thinking_effort")
        if thinking_effort not in ALLOWED_EFFORTS:
            errors.append(
                f"Call {call_index}: thinking_effort '{thinking_effort}' is not allowed"
            )

        request = call.get("request", {})
        response = call.get("response", {}).get("response_data", {})
        messages = request.get("messages", [])
        response_content = response.get("content", [])
        system_blocks = request.get("system")

        if not isinstance(system_blocks, list) or not system_blocks:
            errors.append(f"Call {call_index}: request.system must be a non-empty block list")

        thinking_config = request.get("thinking", {})
        thinking_type = thinking_config.get("type")
        thinking_ok = False
        if thinking_type == "adaptive":
            thinking_ok = True
        elif thinking_type == "enabled" and isinstance(
            thinking_config.get("budget_tokens"), int
        ):
            thinking_ok = thinking_config.get("budget_tokens", 0) > 0
        if not thinking_ok:
            errors.append(
                f"Call {call_index}: request.thinking must be adaptive or enabled with budget_tokens"
            )
        if thinking_type == "adaptive" and "is_garbled" in call:
            errors.append(
                f"Call {call_index}: OpenClaw-style call must not contain is_garbled"
            )
        if thinking_type == "enabled":
            if "is_garbled" not in call:
                errors.append(
                    f"Call {call_index}: Hermes-style call must contain is_garbled"
                )
            elif not isinstance(call.get("is_garbled"), bool):
                errors.append(f"Call {call_index}: is_garbled must be a boolean")

        schema_tool_names = validate_tool_schema(
            call_index, request.get("tools", []), errors
        )

        if not isinstance(messages, list) or not messages:
            errors.append(f"Call {call_index}: request.messages must be a non-empty list")
            messages = []
        elif messages[0].get("role") != "user":
            errors.append(f"Call {call_index}: request.messages[0].role must be 'user'")

        assistant_tool_ids: set[str] = set()
        for message_index, message in enumerate(messages):
            role = message.get("role")
            content = message.get("content")
            if role not in {"user", "assistant"}:
                errors.append(
                    f"Call {call_index}: messages[{message_index}].role '{role}' is invalid"
                )
            if not isinstance(content, list):
                errors.append(
                    f"Call {call_index}: messages[{message_index}].content is not a block list"
                )
                continue
            if role == "assistant":
                validate_assistant_content_blocks(
                    call_index,
                    content,
                    schema_tool_names,
                    errors,
                    assistant_tool_ids,
                )

        if not isinstance(response_content, list):
            errors.append(f"Call {call_index}: response.content is not a block list")
            response_content = []
        validate_assistant_content_blocks(
            call_index,
            response_content,
            schema_tool_names,
            errors,
            assistant_tool_ids,
        )

        stop_reason = response.get("stop_reason")
        if stop_reason not in ALLOWED_STOP_REASONS:
            errors.append(f"Call {call_index}: invalid stop_reason '{stop_reason}'")

        for block in tool_result_blocks(messages):
            if block.get("tool_use_id") not in assistant_tool_ids:
                errors.append(
                    f"Call {call_index}: tool_result.tool_use_id '{block.get('tool_use_id')}' has no matching tool_use"
                )

    if garbled_count:
        warnings.append(f"{garbled_count} calls are marked with is_garbled=true")
    stats["garbled_call_count"] = garbled_count

    assistant_count = len(calls)
    stats["assistant_turns"] = assistant_count
    if assistant_count < 5:
        errors.append(f"assistant turns = {assistant_count} (< 5)")

    last_call = calls[-1]
    last_request_messages = last_call.get("request", {}).get("messages", [])
    last_response = last_call.get("response", {}).get("response_data", {})
    last_response_content = last_response.get("content", [])

    user_messages = [
        message for message in last_request_messages if message.get("role") == "user"
    ]
    cron_count = 0
    for message in user_messages:
        full_text = "\n".join(text_blocks(message.get("content")))
        if any(keyword in full_text for keyword in SPECIAL_KEYWORDS):
            cron_count += 1
    cron_ratio = cron_count / len(user_messages) if user_messages else 0
    stats["cron_ratio"] = cron_ratio
    if cron_ratio >= 0.25:
        errors.append(f"cron/heartbeat/no_reply ratio = {cron_ratio:.1%} (>= 25%)")

    all_tool_results = tool_result_blocks(last_request_messages)
    tool_error_count = sum(1 for block in all_tool_results if tool_result_is_error(block))
    tool_error_ratio = tool_error_count / len(all_tool_results) if all_tool_results else 0
    stats["tool_error_ratio"] = tool_error_ratio
    if tool_error_ratio >= 0.25:
        errors.append(f"tool error ratio = {tool_error_ratio:.1%} (>= 25%)")

    thinking_turn_count = 0
    thinking_after_real_user_only = True
    for call in calls:
        response_content = call.get("response", {}).get("response_data", {}).get("content", [])
        has_thinking = any(
            str(block.get("thinking", "")).strip() for block in thinking_blocks(response_content)
        )
        if not has_thinking:
            continue
        thinking_turn_count += 1
        request_messages = call.get("request", {}).get("messages", [])
        if not request_messages:
            thinking_after_real_user_only = False
            continue
        last_message = request_messages[-1]
        if last_message.get("role") != "user" or not has_non_empty_text(
            last_message.get("content")
        ):
            thinking_after_real_user_only = False

    stats["thinking_density"] = thinking_turn_count / assistant_count if assistant_count else 0
    if thinking_turn_count == 0:
        errors.append("No non-empty thinking block exists in the trajectory")
    if stats["thinking_density"] <= 0.5:
        errors.append(f"thinking density = {stats['thinking_density']:.1%} (<= 50%)")
    if thinking_after_real_user_only and thinking_turn_count > 1:
        errors.append("Thinking appears only on the first assistant turn after each user turn")

    last_stop_reason = last_response.get("stop_reason")
    if last_stop_reason != "end_turn":
        errors.append(
            f"Final call stop_reason is '{last_stop_reason}' (expected 'end_turn')"
        )
    if not has_non_empty_text(last_response_content):
        errors.append("Final call response does not contain a non-empty text block")

    stats["session_id"] = next(iter(session_ids)) if session_ids else session_dir.name
    stats["model"] = model_names[0] if model_names else ""
    stats["thinking_effort"] = calls[0].get("thinking_effort", "")
    stats["latest_timestamp"] = latest_timestamp(calls)

    return len(errors) == 0, errors, warnings, stats


def get_session_latest_mtime(session_dir: Path) -> datetime | None:
    json_files = [
        path
        for path in session_dir.glob("*.json")
        if path.name != "task_difficulty_justification.json"
    ]
    if not json_files:
        return None
    latest_mtime = max(path.stat().st_mtime for path in json_files)
    return datetime.fromtimestamp(latest_mtime)


def process_session_dir(session_dir: Path, pass_dir: Path, fail_dir: Path) -> dict:
    session_id = session_dir.name
    print(f"\n[quality-check] {session_id}")

    try:
        ok, errors, warnings, stats = validate_session(session_dir)
    except Exception as exc:
        print(f"  [error] quality check failed: {exc}")
        import traceback

        traceback.print_exc()
        return {
            "session_id": session_id,
            "status": "error",
            "errors": [str(exc)],
            "warnings": [],
            "stats": {},
        }

    print(
        f"  [stats] turns={stats.get('assistant_turns', 0)} | "
        f"thinking_density={stats.get('thinking_density', 0):.1%} | "
        f"tool_err={stats.get('tool_error_ratio', 0):.1%} | "
        f"cron={stats.get('cron_ratio', 0):.1%}"
    )
    if warnings:
        print(f"  [warnings] {len(warnings)}")
    if errors:
        print(f"  [errors] {len(errors)}")
        for error in errors[:3]:
            print(f"    - {error}")
        if len(errors) > 3:
            print(f"    ... and {len(errors) - 3} more")

    destination_root = pass_dir if ok else fail_dir
    destination = destination_root / session_id
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(session_dir, destination)

    print(f"  [result] {'PASS' if ok else 'FAIL'}")
    return {
        "session_id": session_id,
        "status": "pass" if ok else "fail",
        "errors": errors,
        "warnings": warnings,
        "stats": stats,
    }


def parse_after_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return datetime.strptime(value, "%Y-%m-%d")


def write_reports(report_dir: Path, results: list[dict]) -> None:
    with (report_dir / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(results, handle, ensure_ascii=False, indent=2)

    with (report_dir / "summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "session_id",
                "status",
                "assistant_turns",
                "thinking_density",
                "tool_error_ratio",
                "cron_ratio",
                "garbled_call_count",
                "latest_timestamp",
                "model",
                "thinking_effort",
            ],
        )
        writer.writeheader()
        for result in results:
            stats = result.get("stats", {})
            writer.writerow(
                {
                    "session_id": result.get("session_id", ""),
                    "status": result.get("status", ""),
                    "assistant_turns": stats.get("assistant_turns", ""),
                    "thinking_density": stats.get("thinking_density", ""),
                    "tool_error_ratio": stats.get("tool_error_ratio", ""),
                    "cron_ratio": stats.get("cron_ratio", ""),
                    "garbled_call_count": stats.get("garbled_call_count", ""),
                    "latest_timestamp": stats.get("latest_timestamp", ""),
                    "model": stats.get("model", ""),
                    "thinking_effort": stats.get("thinking_effort", ""),
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run quality checks on Anthropic call-level session folders."
    )
    parser.add_argument("--input_dir", required=True, help="Directory containing session subdirectories.")
    parser.add_argument(
        "--after",
        help="Only process sessions newer than YYYY-MM-DD or YYYY-MM-DD HH:MM:SS.",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    if not input_dir.exists():
        print(f"[error] input directory does not exist: {input_dir}")
        sys.exit(1)

    after_value = args.after if args.after else DEFAULT_AFTER_TIME
    after_time = parse_after_time(after_value) if after_value else None

    output_root = input_dir.parent / f"{input_dir.name}-质检结果"
    pass_dir = output_root / "pass"
    fail_dir = output_root / "fail"
    report_dir = output_root / "report"
    for path in (pass_dir, fail_dir, report_dir):
        path.mkdir(parents=True, exist_ok=True)

    session_dirs = [
        item
        for item in input_dir.iterdir()
        if item.is_dir() and any(item.glob("*.json"))
    ]
    if after_time is not None:
        filtered = []
        for session_dir in session_dirs:
            latest = get_session_latest_mtime(session_dir)
            if latest is None or latest >= after_time:
                filtered.append(session_dir)
        session_dirs = filtered

    if not session_dirs:
        print("[error] no valid session directories found")
        sys.exit(1)

    print(f"[input] {input_dir}")
    print(f"[output] {output_root}")
    if after_time is not None:
        print(f"[after] {after_time:%Y-%m-%d %H:%M:%S}")

    results = [process_session_dir(session_dir, pass_dir, fail_dir) for session_dir in session_dirs]
    write_reports(report_dir, results)

    passed = sum(1 for result in results if result.get("status") == "pass")
    failed = sum(1 for result in results if result.get("status") == "fail")
    errored = sum(1 for result in results if result.get("status") == "error")
    print(f"\n[summary] pass={passed} fail={failed} error={errored}")
    print(f"[done] {output_root}")


if __name__ == "__main__":
    main()
