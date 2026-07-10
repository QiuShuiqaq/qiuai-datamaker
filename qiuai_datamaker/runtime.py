from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def get_resource_root() -> Path:
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return get_project_root()


def get_icon_path() -> Path:
    resource_root = get_resource_root()
    frozen_icon = resource_root / "icon" / "Q1.ico"
    if frozen_icon.exists():
        return frozen_icon
    dev_ico = get_project_root() / "icon" / "Q1.ico"
    if dev_ico.exists():
        return dev_ico
    return get_project_root() / "icon" / "Q1.png"


def get_app_root() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return get_project_root()


def get_data_root(app_name: str) -> Path:
    if is_frozen():
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / app_name / "DATA"
        return Path.home() / "AppData" / "Local" / app_name / "DATA"
    return get_project_root() / "DATA"
