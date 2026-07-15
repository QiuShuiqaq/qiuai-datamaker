#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from openai import OpenAI


PROMPT_TEMPLATE = """You are an **Expert Software Engineering Analyst**. Your goal is to analyze a given software engineering task trajectory (a conversation between a user and an AI assistant, including code changes, reasoning, and tool usage) and accurately classify its **Task Difficulty Level**.

## Evaluation Criteria & Process

Do not judge difficulty purely by the length of the conversation or the volume of boilerplate code generated. Before making a decision, mentally analyze the following factors to form your justification:
1. **Reasoning Steps & Tool Usage**: Did the assistant solve it in one shot, or did it require multi-step deduction, multi-turn tool execution (e.g., debugging loops), and handling ambiguity?
2. **Context & Scope**: Is it a localized change, or does it involve cross-system integration and complex dependencies?
3. **Domain Knowledge**: Does it rely on basic programming knowledge, or does it require specialized, system-level, or cutting-edge domain expertise?

## Task Difficulty Scale

Choose exactly one of the following levels:

**1. `low` (Trivial / Basic)**
- **Criteria**: Simple tasks requiring minimal reasoning or coding.
- **Examples**: Daily Q&A, formatting adjustments, syntax corrections, basic calculations, text modifications, single-step simple tool usage.

**2. `medium` (Moderate / Standard Development)**
- **Criteria**: Tasks with a clear scope and moderate complexity.
- **Examples**: Standard feature implementation (e.g., typical CRUD), writing unit tests for explicit functions, straightforward bug fixes within a single module, localized data processing.

**3. `high` (Complex / Multi-step Reasoning)**
- **Criteria**: Requires multi-step reasoning, multi-turn tool usage, or deep thinking.
- **Examples**: Complex debugging requiring tracing state across files, cross-system integration, refactoring medium-sized codebases, handling asynchronous logic or standard architectural design.

**4. `xhigh` (Advanced / System-Level / Long Toolchain)**
- **Criteria**: Requires extensive domain knowledge, long-range toolchains, or deep system-level troubleshooting.
- **Examples**: Complex algorithm implementation, performance optimization/profiling, resolving memory leaks, system-level networking issues, handling distributed system anomalies.

**5. `expert` (Specialized / Cutting-Edge)**
- **Criteria**: Requires a senior domain expert to resolve. Highly specialized professional judgment.
- **Examples**: Designing novel algorithms, resolving undocumented zero-day vulnerabilities, writing custom compilers, complex reverse engineering, cutting-edge machine learning architectures.

### Input Trajectory

Below is the task trajectory you need to evaluate:

<trajectory>
{trajectory_content}
</trajectory>

### Output Format

Provide your response strictly in the following JSON format. Do not include markdown code blocks in the output, just the raw JSON:

{{
  "justification": "Briefly analyze the tool usage, reasoning steps, and technical depth, then explain exactly why it fits the chosen level and not the adjacent levels.",
  "difficulty": "low | medium | high | xhigh | expert"
}}
"""

ALLOWED_DIFFICULTIES = {"low", "medium", "high", "xhigh", "expert"}


def _call_sort_key(file_path: Path) -> tuple[int, float]:
    match = re.match(r"^(\d+)_", file_path.stem)
    if match:
        return int(match.group(1)), file_path.stat().st_mtime
    if file_path.stem.isdigit():
        return int(file_path.stem), file_path.stat().st_mtime
    return -1, file_path.stat().st_mtime


def find_last_call_file(session_dir: Path) -> Path | None:
    call_files = [
        file_path
        for file_path in session_dir.glob("*.json")
        if file_path.name != "task_difficulty_justification.json"
    ]
    if not call_files:
        return None
    call_files.sort(key=_call_sort_key, reverse=True)
    return call_files[0]


def normalize_reply(
    reply: str,
    session_id: str,
    evaluation_time: str,
    api_base: str,
) -> tuple[dict, str]:
    parsed = json.loads(reply)
    difficulty = str(parsed.get("difficulty") or parsed.get("task_difficulty", "")).strip().lower()
    justification = str(parsed.get("justification", "")).strip()
    if not difficulty:
        raise ValueError("missing task_difficulty")
    if difficulty not in ALLOWED_DIFFICULTIES:
        allowed = ", ".join(sorted(ALLOWED_DIFFICULTIES))
        raise ValueError(f"invalid task_difficulty '{difficulty}' (allowed: {allowed})")
    if not justification:
        raise ValueError("missing justification")
    normalized = {
        "session_id": session_id,
        "evaluation_time": evaluation_time,
        "api_base": api_base,
        "justification": justification,
        "task_difficulty": difficulty,
    }
    return normalized, difficulty


def main() -> None:
    parser = argparse.ArgumentParser(description="Run DeepSeek difficulty labeling on pass sessions.")
    parser.add_argument("--input_dir", required=True, help="Directory containing pass session folders.")
    parser.add_argument("--api_key", required=True, help="DeepSeek API key.")
    parser.add_argument(
        "--api_base",
        default="https://api.deepseek.com",
        help="DeepSeek API base URL.",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    if not input_dir.exists():
        print(f"[error] input directory does not exist: {input_dir}")
        sys.exit(1)

    labels_dir = input_dir.parent / "difficulty_labels"
    labels_dir.mkdir(parents=True, exist_ok=True)
    session_dirs = [item for item in input_dir.iterdir() if item.is_dir()]

    print("=" * 60)
    print("DeepSeek difficulty labeling")
    print("=" * 60)
    print(f"[input] {input_dir}")
    print(f"[labels] {labels_dir}")
    print(f"[sessions] {len(session_dirs)}")

    client = OpenAI(api_key=args.api_key, base_url=args.api_base)
    success_count = 0

    for index, session_dir in enumerate(session_dirs, start=1):
        session_id = session_dir.name
        print(f"[{index}/{len(session_dirs)}] {session_id}")
        last_call = find_last_call_file(session_dir)
        if last_call is None:
            normalized = {
                "session_id": session_id,
                "evaluation_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "api_base": args.api_base,
                "justification": "No call file found",
                "task_difficulty": "",
            }
            difficulty = ""
            print("  [skip] no call file")
        else:
            with last_call.open("r", encoding="utf-8") as handle:
                content = handle.read().strip()
            prompt = PROMPT_TEMPLATE.format(trajectory_content=content)
            try:
                response = client.chat.completions.create(
                    model="deepseek-v4-pro",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                )
                reply = response.choices[0].message.content.strip()
                normalized, difficulty = normalize_reply(
                    reply,
                    session_id,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    args.api_base,
                )
                if difficulty in ALLOWED_DIFFICULTIES:
                    success_count += 1
                print(f"  [done] difficulty={difficulty or 'empty'}")
            except Exception as exc:
                normalized = {
                    "session_id": session_id,
                    "evaluation_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "api_base": args.api_base,
                    "justification": str(exc),
                    "task_difficulty": "",
                }
                difficulty = ""
                print(f"  [error] {exc}")

        label_file = labels_dir / f"{session_id}.json"
        with label_file.open("w", encoding="utf-8") as handle:
            json.dump(normalized, handle, ensure_ascii=False, indent=4)

        justification_file = session_dir / "task_difficulty_justification.json"
        with justification_file.open("w", encoding="utf-8") as handle:
            json.dump(normalized, handle, ensure_ascii=False, indent=4)

    print(f"\n[summary] success={success_count}/{len(session_dirs)}")
    print(f"[done] labels written to {labels_dir}")


if __name__ == "__main__":
    main()
