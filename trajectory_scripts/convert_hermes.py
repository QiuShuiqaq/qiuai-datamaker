import argparse
import copy
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")


MODEL_NAME_MAP = {
    "claude-opus-4-6": "claude-opus-4-6",
    "claude-opus-4-7": "claude-opus-4-7",
    "claude-opus-4-8": "claude-opus-4-8",
}

BUILTIN_TOOLS = {
    "read": {
        "name": "read",
        "description": "Read the contents of a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "offset": {"type": "number"},
                "limit": {"type": "number"},
            },
            "required": ["path"],
        },
    },
    "write": {
        "name": "write",
        "description": "Write content to a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    "edit": {
        "name": "edit",
        "description": "Edit a file using exact text replacement.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "edits": {"type": "array"},
            },
            "required": ["path", "edits"],
        },
    },
    "exec": {
        "name": "exec",
        "description": "Execute shell commands.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    "terminal": {
        "name": "terminal",
        "description": "Execute terminal commands.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    "web_search": {
        "name": "web_search",
        "description": "Search the web.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    "web_fetch": {
        "name": "web_fetch",
        "description": "Fetch content from URL.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    "process": {
        "name": "process",
        "description": "Manage running processes.",
        "input_schema": {
            "type": "object",
            "properties": {"action": {"type": "string"}},
            "required": ["action"],
        },
    },
}

ERROR_MARKERS = (
    '"status": "error"',
    '"status":"error"',
    '"success": false',
    '"success":false',
)

MOJIBAKE_MARKERS = ("\ufffd",)


def extract_system_prompt(hermes_data: dict) -> str:
    return hermes_data.get("system_prompt", "You are a helpful AI assistant.")


def build_system_blocks(system_text: str) -> list[dict]:
    return [
        {
            "type": "text",
            "text": system_text,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def build_tools_list(used_tool_names: set[str]) -> list[dict]:
    tools = []
    for name in sorted(used_tool_names):
        if name in BUILTIN_TOOLS:
            tools.append(copy.deepcopy(BUILTIN_TOOLS[name]))
        else:
            tools.append(
                {
                    "name": name,
                    "description": f"Tool: {name}",
                    "input_schema": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                }
            )
    return tools


def normalize_thinking_effort(value) -> str:
    if value in {"high", "xhigh", "max"}:
        return value
    return "high"


def normalize_timestamp(value) -> str:
    if isinstance(value, (int, float)):
        return (
            datetime.fromtimestamp(value / 1000, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
                "+00:00", "Z"
            )
        if text.endswith("Z"):
            return text
        if text.endswith("+00:00"):
            return text.replace("+00:00", "Z")
        return f"{text}Z"
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def looks_garbled_text(text: str) -> bool:
    if not isinstance(text, str) or not text:
        return False
    if "\ufffd" in text:
        return True
    score = sum(text.count(marker) for marker in MOJIBAKE_MARKERS)
    return score >= 4


def object_contains_garbled(value) -> bool:
    if isinstance(value, str):
        return looks_garbled_text(value)
    if isinstance(value, list):
        return any(object_contains_garbled(item) for item in value)
    if isinstance(value, dict):
        return any(object_contains_garbled(item) for item in value.values())
    return False


def safe_json_loads(raw_value):
    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
        except Exception:
            return {"raw": raw_value}
        return parsed if isinstance(parsed, dict) else {"raw": parsed}
    if isinstance(raw_value, dict):
        return raw_value
    return {"raw": raw_value}


def parse_reasoning_details(reasoning_details):
    if not reasoning_details:
        return None
    try:
        details = (
            json.loads(reasoning_details)
            if isinstance(reasoning_details, str)
            else reasoning_details
        )
    except Exception:
        return None
    if isinstance(details, dict):
        details = [details]
    if not isinstance(details, list):
        return None
    for item in details:
        if isinstance(item, dict) and item.get("type") == "thinking":
            thinking = item.get("thinking", "")
            if str(thinking).strip():
                return {
                    "thinking": thinking,
                    "signature": item.get("signature") or "Eo8E_placeholder_sig",
                }
    return None


def convert_hermes_message_to_anthropic(message: dict):
    role = message.get("role")
    if role == "user":
        content = message.get("content", "")
        return [{"type": "text", "text": content if str(content).strip() else " "}]

    if role == "assistant":
        blocks = []
        thinking_data = parse_reasoning_details(message.get("reasoning_details"))
        if thinking_data:
            blocks.append(
                {
                    "type": "thinking",
                    "thinking": thinking_data["thinking"],
                    "signature": thinking_data["signature"],
                }
            )

        content = message.get("content", "")
        if isinstance(content, str) and content.strip():
            blocks.append({"type": "text", "text": content})

        for tool_call in message.get("tool_calls") or []:
            function = tool_call.get("function", {})
            blocks.append(
                {
                    "type": "tool_use",
                    "id": tool_call.get("id")
                    or tool_call.get("call_id")
                    or f"toolu_{uuid.uuid4().hex[:12]}",
                    "name": function.get("name", "unknown"),
                    "input": safe_json_loads(function.get("arguments", {})),
                }
            )
        return blocks

    if role == "tool":
        return None

    return [{"type": "text", "text": str(message.get("content", ""))}]


def convert_tool_result_to_block(message: dict) -> dict:
    content = message.get("content", "")
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    result = {
        "type": "tool_result",
        "tool_use_id": message.get("tool_call_id")
        or message.get("toolCallId")
        or "unknown",
        "content": content or "",
    }
    lowered = result["content"].lower()
    if any(marker in lowered for marker in ERROR_MARKERS):
        result["is_error"] = True
    return result


def process_hermes_json(json_path, system_prompt):
    with open(json_path, "r", encoding="utf-8") as handle:
        hermes_data = json.load(handle)

    session_id = hermes_data.get("id", Path(json_path).stem)
    raw_model = hermes_data.get("model", "claude-opus-4-6")
    model_name = MODEL_NAME_MAP.get(raw_model, raw_model)

    model_config = hermes_data.get("model_config", {})
    if isinstance(model_config, str):
        try:
            model_config = json.loads(model_config)
        except Exception:
            model_config = {}
    reasoning_config = model_config.get("reasoning_config", {})
    thinking_effort = normalize_thinking_effort(
        reasoning_config.get("effort", "high")
        if reasoning_config.get("enabled", True)
        else "high"
    )
    max_tokens = model_config.get("max_tokens") or 16384
    temperature = model_config.get("temperature", 1.0)
    budget_tokens = reasoning_config.get("budget_tokens") or 4096

    messages = hermes_data.get("messages", [])
    all_tool_names = set()
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for tool_call in message.get("tool_calls") or []:
            function = tool_call.get("function", {})
            name = function.get("name")
            if name:
                all_tool_names.add(name)

    system_blocks = build_system_blocks(system_prompt)
    tools_list = build_tools_list(all_tool_names)

    calls: list[dict] = []
    anthropic_messages: list[dict] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        role = message.get("role")

        if role == "user":
            anthropic_messages.append(
                {
                    "role": "user",
                    "content": convert_hermes_message_to_anthropic(message),
                }
            )
            index += 1
            continue

        if role != "assistant":
            index += 1
            continue

        if not anthropic_messages or anthropic_messages[0].get("role") != "user":
            anthropic_messages.insert(
                0,
                {"role": "user", "content": [{"type": "text", "text": "[session start]"}]},
            )

        response_blocks = convert_hermes_message_to_anthropic(message)
        next_index = index + 1
        tool_results = []
        while next_index < len(messages) and messages[next_index].get("role") == "tool":
            tool_results.append(messages[next_index])
            next_index += 1

        finish_reason = message.get("finish_reason")
        if finish_reason == "tool_calls":
            stop_reason = "tool_use"
        elif finish_reason == "max_tokens":
            stop_reason = "max_tokens"
        elif finish_reason == "stop_sequence":
            stop_reason = "stop_sequence"
        else:
            stop_reason = "end_turn"

        usage_block = {
            "input_tokens": message.get("prompt_tokens", 0),
            "output_tokens": message.get("token_count", 0)
            or message.get("completion_tokens", 0),
        }

        request_messages = copy.deepcopy(anthropic_messages)
        response_id = (
            message.get("response_id")
            or message.get("id")
            or f"msg_{uuid.uuid4().hex[:24]}"
        )
        request_id = (
            message.get("request_id")
            or message.get("requestId")
            or message.get("x_request_id")
            or message.get("x-request-id")
            or f"msg_{uuid.uuid4().hex[:24]}"
        )

        call_record = {
            "session_id": session_id,
            "request_id": request_id,
            "timestamp": normalize_timestamp(message.get("timestamp")),
            "thinking_effort": thinking_effort,
            "is_garbled": bool(
                object_contains_garbled(system_blocks)
                or object_contains_garbled(request_messages)
                or object_contains_garbled(response_blocks)
            ),
            "request": {
                "model": model_name,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "thinking": {"type": "enabled", "budget_tokens": budget_tokens},
                "system": copy.deepcopy(system_blocks),
                "tools": copy.deepcopy(tools_list),
                "messages": request_messages,
            },
            "response": {
                "response_data": {
                    "id": response_id,
                    "type": "message",
                    "role": "assistant",
                    "model": model_name,
                    "content": copy.deepcopy(response_blocks),
                    "stop_reason": stop_reason,
                    "stop_sequence": None,
                    "usage": usage_block,
                }
            },
        }

        calls.append(call_record)
        anthropic_messages.append(
            {"role": "assistant", "content": copy.deepcopy(response_blocks)}
        )
        if tool_results:
            anthropic_messages.append(
                {
                    "role": "user",
                    "content": [convert_tool_result_to_block(item) for item in tool_results],
                }
            )

        index = next_index

    return calls, model_name, all_tool_names


def convert_file(json_path, target_dir, system_prompt_override=None):
    print(f"\n{'=' * 60}")
    print(f"[processing] {json_path}")

    try:
        with open(json_path, "r", encoding="utf-8") as handle:
            hermes_data = json.load(handle)
        system_prompt = system_prompt_override or extract_system_prompt(hermes_data)
        calls, model_name, tool_names = process_hermes_json(json_path, system_prompt)
    except Exception as exc:
        print(f"  [error] parse failed: {exc}")
        import traceback

        traceback.print_exc()
        return None

    if not calls:
        print("  [skip] no valid calls")
        return None

    session_id = calls[0]["session_id"]
    session_dir = Path(target_dir) / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    for index, call in enumerate(calls):
        output_file = session_dir / f"{index:04d}_{call['request_id']}.json"
        with output_file.open("w", encoding="utf-8") as handle:
            json.dump(call, handle, ensure_ascii=False, indent=2)

    print(f"  [session] {session_id}")
    print(f"  [model] {model_name}")
    print(f"  [calls] {len(calls)}")
    print(f"  [tools] {', '.join(sorted(tool_names)) if tool_names else 'None'}")
    print(f"  [output] {session_dir}")

    return {
        "file": Path(json_path).name,
        "session_id": session_id,
        "model": model_name,
        "calls": len(calls),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Convert Hermes JSON into Anthropic call-level JSON.",
    )
    parser.add_argument("--input_dir", required=True, help="Directory containing .json files.")
    parser.add_argument("--output_dir", help="Output directory. Defaults to a sibling folder.")
    parser.add_argument("--system_prompt", help="Override system prompt.")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    if not input_dir.exists():
        print(f"[error] input directory does not exist: {input_dir}")
        sys.exit(1)

    if args.output_dir:
        target_dir = Path(args.output_dir)
    else:
        target_dir = input_dir.parent / f"{input_dir.name}-待质检数据-{datetime.now():%Y%m%d}"

    json_files = sorted(
        path
        for path in input_dir.glob("*.json")
        if path.parent == input_dir and not path.name.startswith(".")
    )
    if not json_files:
        print(f"[error] no .json files found: {input_dir}")
        sys.exit(1)

    print(f"[input] {input_dir}")
    print(f"[output] {target_dir}")
    print(f"[files] {len(json_files)}")

    target_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for json_file in json_files:
        result = convert_file(str(json_file), str(target_dir), args.system_prompt)
        if result:
            results.append(result)

    print(f"\n{'=' * 60}")
    print(f"[summary] converted {len(results)}/{len(json_files)} files")
    print("=" * 60)
    for result in results:
        print(f"  - {result['file']} -> {result['calls']} calls | model: {result['model']}")
    print(f"\n[done] {target_dir}")


if __name__ == "__main__":
    main()
