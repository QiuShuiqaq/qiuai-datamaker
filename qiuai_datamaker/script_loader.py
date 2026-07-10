from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path
from types import ModuleType

from .constants import SCRIPT_ROOT


def _load_module(module_name: str, file_path: Path) -> ModuleType:
    if not file_path.exists():
        raise FileNotFoundError(
            f"Required script resource not found: {file_path}. "
            "Check the packaged trajectory_scripts resources."
        )
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=4)
def get_convert_openclaw_module() -> ModuleType:
    return _load_module("convert_openclaw_bridge", SCRIPT_ROOT / "convert_openclaw.py")


@lru_cache(maxsize=4)
def get_convert_hermes_module() -> ModuleType:
    return _load_module("convert_hermes_bridge", SCRIPT_ROOT / "convert_hermes.py")


@lru_cache(maxsize=4)
def get_quality_check_module() -> ModuleType:
    return _load_module("quality_check_bridge", SCRIPT_ROOT / "quality_check.py")


@lru_cache(maxsize=4)
def get_label_module() -> ModuleType:
    return _load_module(
        "batch_deepseek_simple_bridge", SCRIPT_ROOT / "batch_deepseek_simple.py"
    )
