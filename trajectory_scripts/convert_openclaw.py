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
    "claude-opus-4-6-thinking": "claude-opus-4-6",
    "claude-opus-4-6": "claude-opus-4-6",
    "claude-opus-4-7-thinking": "claude-opus-4-7",
    "claude-opus-4-7": "claude-opus-4-7",
    "claude-opus-4-8-thinking": "claude-opus-4-8",
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
    "sessions_spawn": {
        "name": "sessions_spawn",
        "description": "Spawn sub-agent session.",
        "input_schema": {
            "type": "object",
            "properties": {"task": {"type": "string"}},
            "required": ["task"],
        },
    },
    "sessions_list": {
        "name": "sessions_list",
        "description": "List sessions.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    "sessions_history": {
        "name": "sessions_history",
        "description": "Get session history.",
        "input_schema": {
            "type": "object",
            "properties": {"sessionKey": {"type": "string"}},
            "required": ["sessionKey"],
        },
    },
    "sessions_send": {
        "name": "sessions_send",
        "description": "Send message to session.",
        "input_schema": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    },
    "sessions_yield": {
        "name": "sessions_yield",
        "description": "Yield current turn.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    "subagents": {
        "name": "subagents",
        "description": "Manage sub-agents.",
        "input_schema": {
            "type": "object",
            "properties": {"action": {"type": "string"}},
            "required": ["action"],
        },
    },
    "session_status": {
        "name": "session_status",
        "description": "Show session status.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    "update_plan": {
        "name": "update_plan",
        "description": "Update work plan.",
        "input_schema": {
            "type": "object",
            "properties": {"plan": {"type": "array"}},
            "required": ["plan"],
        },
    },
    "cron": {
        "name": "cron",
        "description": "Manage cron jobs.",
        "input_schema": {
            "type": "object",
            "properties": {"action": {"type": "string"}},
            "required": ["action"],
        },
    },
    "memory_search": {
        "name": "memory_search",
        "description": "Search memory.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    "memory_get": {
        "name": "memory_get",
        "description": "Get memory content.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
}

ERROR_MARKERS = (
    '"status": "error"',
    '"status":"error"',
    '"success": false',
    '"success":false',
)

MOJIBAKE_MARKERS = (
    "\ufffd",
    "锟",
    "鈥",
    "銆",
    "锛",
    "鍚",
    "鏄",
    "鐨",
    "浣",
    "鎴",
    "鍙",
    "鏈",
    "闂",
    "璇",
    "瀵",
    "浠",
)


def get_system_prompt() -> str:
    return "You are a personal assistant running inside OpenClaw."


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


def normalize_model_name(raw_model: str) -> str:
    return MODEL_NAME_MAP.get(raw_model, raw_model)


def normalize_thinking_effort(value) -> str:
    if isinstance(value, dict):
        value = value.get("type")
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


def collect_tool_names_from_message(message: dict) -> set[str]:
    tool_names: set[str] = set()
    content = message.get("content", [])
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") in {"toolCall", "tool_use"} and block.get("name"):
                tool_names.add(block["name"])
    for tool_call in message.get("tool_calls") or []:
        function = tool_call.get("function", {})
        name = function.get("name")
        if name:
            tool_names.add(name)
    return tool_names


def convert_assistant_content_to_blocks(message: dict) -> list[dict]:
    blocks: list[dict] = []
    content = message.get("content", [])

    if isinstance(content, str):
        if content.strip():
            blocks.append({"type": "text", "text": content})
        return blocks

    for block in content:
        if isinstance(block, str):
            if block.strip():
                blocks.append({"type": "text", "text": block})
            continue
        if not isinstance(block, dict):
            continue

        block_type = block.get("type")
        if block_type == "thinking":
            thinking_text = block.get("thinking", "")
            if str(thinking_text).strip():
                blocks.append(
                    {
                        "type": "thinking",
                        "thinking": thinking_text,
                        "signature": block.get("thinkingSignature")
                        or block.get("signature")
                        or "Eo8E_placeholder_sig",
                    }
                )
        elif block_type == "text":
            text = block.get("text", "")
            if str(text).strip():
                blocks.append({"type": "text", "text": text})
        elif block_type == "toolCall":
            blocks.append(
                {
                    "type": "tool_use",
                    "id": block.get("id") or f"toolu_{uuid.uuid4().hex[:12]}",
                    "name": block.get("name", "unknown"),
                    "input": safe_json_loads(block.get("arguments", {})),
                }
            )
        elif block_type == "tool_use":
            normalized_block = copy.deepcopy(block)
            normalized_block["input"] = safe_json_loads(normalized_block.get("input", {}))
            normalized_block["id"] = normalized_block.get("id") or f"toolu_{uuid.uuid4().hex[:12]}"
            normalized_block["name"] = normalized_block.get("name", "unknown")
            blocks.append(normalized_block)

    for tool_call in message.get("tool_calls") or []:
        function = tool_call.get("function", {})
        blocks.append(
            {
                "type": "tool_use",
                "id": tool_call.get("id") or f"toolu_{uuid.uuid4().hex[:12]}",
                "name": function.get("name", "unknown"),
                "input": safe_json_loads(function.get("arguments", {})),
            }
        )

    return blocks


def convert_tool_message_to_result(message: dict) -> dict:
    content = message.get("content", "")

    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
            else:
                parts.append(json.dumps(block, ensure_ascii=False))
        content = "\n".join(part for part in parts if part)
    elif not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)

    result = {
        "type": "tool_result",
        "tool_use_id": message.get("tool_call_id")
        or message.get("toolCallId")
        or "unknown",
        "content": content or "",
    }
    lowered = result["content"].lower() if isinstance(result["content"], str) else ""
    if any(marker in lowered for marker in ERROR_MARKERS):
        result["is_error"] = True
    return result


def convert_user_content_to_blocks(message: dict) -> list[dict]:
    content = message.get("content", "")
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content.strip() else [{"type": "text", "text": " "}]

    if not isinstance(content, list):
        return [{"type": "text", "text": str(content)}]

    blocks: list[dict] = []
    for item in content:
        if isinstance(item, str):
            blocks.append({"type": "text", "text": item})
        elif isinstance(item, dict):
            blocks.append(copy.deepcopy(item))
    return blocks or [{"type": "text", "text": " "}]


def parse_jsonl_or_stream(content: str) -> list[dict]:
    events: list[dict] = []
    lines = content.splitlines()
    first_line = next((line.strip() for line in lines if line.strip()), "")

    if first_line.startswith("{") and first_line.endswith("}"):
        for line in lines:
            line = line.strip()
            if line:
                events.append(json.loads(line))
        return events

    decoder = json.JSONDecoder()
    position = 0
    raw = content.strip()
    while position < len(raw):
        while position < len(raw) and raw[position] in " \t\r\n":
            position += 1
        if position >= len(raw):
            break
        item, end_position = decoder.raw_decode(raw, position)
        events.append(item)
        position = end_position
    return events


def process_openclaw_jsonl(jsonl_path, system_prompt):
    with open(jsonl_path, "r", encoding="utf-8") as handle:
        events = parse_jsonl_or_stream(handle.read())

    session_id = Path(jsonl_path).stem
    raw_model = "claude-opus-4-6"
    thinking_effort = "high"
    temperature = 1.0
    max_tokens = 16384
    observed_system_prompt = system_prompt

    messages: list[dict] = []
    message_timestamps: list[object] = []

    for event in events:
        event_type = event.get("type", "")
        if event_type == "session":
            session_id = event.get("id", session_id)
        elif event_type == "model_change":
            raw_model = event.get("modelId", raw_model)
        elif event_type == "thinking_level_change":
            thinking_effort = event.get("thinkingLevel", thinking_effort)
        elif event_type == "message":
            message = event.get("message", {})
            role = message.get("role")
            if role == "system":
                if isinstance(message.get("content"), str) and message["content"].strip():
                    observed_system_prompt = message["content"]
                continue
            if role in {"user", "assistant", "tool", "toolResult"}:
                messages.append(message)
                message_timestamps.append(message.get("timestamp") or event.get("timestamp"))

    model_name = normalize_model_name(raw_model)
    thinking_effort = normalize_thinking_effort(thinking_effort)
    all_tool_names = set()
    for message in messages:
        if message.get("role") == "assistant":
            all_tool_names.update(collect_tool_names_from_message(message))

    tools_list = build_tools_list(all_tool_names)
    system_blocks = build_system_blocks(observed_system_prompt)

    calls: list[dict] = []
    anthropic_messages: list[dict] = []

    for index, message in enumerate(messages):
        role = message.get("role")
        if role == "user":
            anthropic_messages.append(
                {
                    "role": "user",
                    "content": convert_user_content_to_blocks(message),
                }
            )
            continue

        if role in {"tool", "toolResult"}:
            tool_result = convert_tool_message_to_result(message)
            if anthropic_messages and anthropic_messages[-1]["role"] == "user":
                anthropic_messages[-1]["content"].append(tool_result)
            else:
                anthropic_messages.append({"role": "user", "content": [tool_result]})
            continue

        if role != "assistant":
            continue

        if not anthropic_messages or anthropic_messages[0].get("role") != "user":
            anthropic_messages.insert(
                0,
                {"role": "user", "content": [{"type": "text", "text": "[session start]"}]},
            )

        response_blocks = convert_assistant_content_to_blocks(message)
        raw_stop = message.get("stopReason", "")
        stop_reason_map = {
            "stop": "end_turn",
            "end_turn": "end_turn",
            "tool_use": "tool_use",
            "max_tokens": "max_tokens",
            "stop_sequence": "stop_sequence",
        }
        if raw_stop in stop_reason_map:
            stop_reason = stop_reason_map[raw_stop]
        else:
            stop_reason = (
                "tool_use"
                if any(block.get("type") == "tool_use" for block in response_blocks)
                else "end_turn"
            )

        usage = message.get("usage", {})
        if usage:
            usage_block = {
                "input_tokens": usage.get("input", 0),
                "output_tokens": usage.get("output", 0),
                "cache_read_input_tokens": usage.get("cacheRead", 0),
                "cache_creation_input_tokens": usage.get("cacheWrite", 0),
            }
        else:
            usage_block = {
                "input_tokens": len(json.dumps(anthropic_messages, ensure_ascii=False)) // 4,
                "output_tokens": len(json.dumps(response_blocks, ensure_ascii=False)) // 4,
                "cache_read_input_tokens": 0,
            }

        request_messages = copy.deepcopy(anthropic_messages)
        call_record = {
            "session_id": session_id,
            "request_id": message.get("requestId")
            or message.get("x-request-id")
            or message.get("x_request_id")
            or str(uuid.uuid4()),
            "timestamp": normalize_timestamp(
                message_timestamps[index] if index < len(message_timestamps) else None
            ),
            "thinking_effort": thinking_effort,
            "request": {
                "model": model_name,
                "max_tokens": max_tokens,
                "thinking": {"type": "adaptive"},
                "temperature": temperature,
                "system": copy.deepcopy(system_blocks),
                "tools": copy.deepcopy(tools_list),
                "messages": request_messages,
            },
            "response": {
                "response_data": {
                    "id": message.get("responseId") or f"msg_{uuid.uuid4().hex[:16]}",
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

        if object_contains_garbled(system_blocks) or object_contains_garbled(
            request_messages
        ) or object_contains_garbled(response_blocks):
            call_record["is_garbled"] = True

        calls.append(call_record)
        anthropic_messages.append(
            {"role": "assistant", "content": copy.deepcopy(response_blocks)}
        )

    return calls, model_name, all_tool_names


def convert_file(jsonl_path, target_dir, system_prompt):
    print(f"\n{'=' * 60}")
    print(f"[processing] {jsonl_path}")

    try:
        calls, model_name, tool_names = process_openclaw_jsonl(jsonl_path, system_prompt)
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
        "file": Path(jsonl_path).name,
        "session_id": session_id,
        "model": model_name,
        "calls": len(calls),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Convert OpenClaw JSONL into Anthropic call-level JSON.",
    )
    parser.add_argument("--input_dir", required=True, help="Directory containing .jsonl files.")
    parser.add_argument("--output_dir", help="Output directory. Defaults to a sibling folder.")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    if not input_dir.exists():
        print(f"[error] input directory does not exist: {input_dir}")
        sys.exit(1)

    if args.output_dir:
        target_dir = Path(args.output_dir)
    else:
        target_dir = input_dir.parent / f"{input_dir.name}-待质检数据-{datetime.now():%Y%m%d}"

    jsonl_files = sorted(path for path in input_dir.glob("*.jsonl") if path.parent == input_dir)
    if not jsonl_files:
        print(f"[error] no .jsonl files found: {input_dir}")
        sys.exit(1)

    print(f"[input] {input_dir}")
    print(f"[output] {target_dir}")
    print(f"[files] {len(jsonl_files)}")

    target_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for jsonl_file in jsonl_files:
        result = convert_file(str(jsonl_file), str(target_dir), get_system_prompt())
        if result:
            results.append(result)

    print(f"\n{'=' * 60}")
    print(f"[summary] converted {len(results)}/{len(jsonl_files)} files")
    print("=" * 60)
    for result in results:
        print(f"  - {result['file']} -> {result['calls']} calls | model: {result['model']}")
    print(f"\n[done] {target_dir}")


if __name__ == "__main__":
    main()
