from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path
from types import ModuleType

from .constants import SCRIPT_ROOT
from .runtime import get_project_root


def _candidate_script_roots() -> list[Path]:
    project_root = get_project_root()
    return [
        SCRIPT_ROOT,
        project_root / "trajectory_scripts",
        project_root.parent / "trajectory_data_code" / "阿里脚本",
        project_root.parent / "Opus 真实用户日志验收标准 - openclaw_hermes" / "图片和附件",
    ]


def _resolve_script_path(filename: str) -> Path:
    for root in _candidate_script_roots():
        candidate = root / filename
        if candidate.exists():
            return candidate
    searched = "\n".join(str(root / filename) for root in _candidate_script_roots())
    raise FileNotFoundError(
        f"Required script resource not found: {filename}\nSearched:\n{searched}"
    )


def _load_module(module_name: str, file_path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=4)
def get_convert_openclaw_module() -> ModuleType:
    return _load_module("convert_openclaw_bridge", _resolve_script_path("convert_openclaw.py"))


@lru_cache(maxsize=4)
def get_convert_hermes_module() -> ModuleType:
    return _load_module("convert_hermes_bridge", _resolve_script_path("convert_hermes.py"))


@lru_cache(maxsize=4)
def get_quality_check_module() -> ModuleType:
    return _load_module("quality_check_bridge", _resolve_script_path("quality_check.py"))


@lru_cache(maxsize=4)
def get_label_module() -> ModuleType:
    return _load_module("batch_deepseek_simple_bridge", _resolve_script_path("batch_deepseek_simple.py"))
