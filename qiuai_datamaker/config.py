from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .constants import CONFIG_PATH


@dataclass
class AppConfig:
    openclaw_source_dir: str = ""
    hermes_source_dir: str = ""
    deepseek_api_key: str = ""
    deepseek_api_base: str = "https://api.deepseek.com"
    export_dir: str = ""
    language: str = "zh_CN"


class ConfigStore:
    def __init__(self, path: Path = CONFIG_PATH) -> None:
        self.path = path

    def load(self) -> AppConfig:
        if not self.path.exists():
            return AppConfig()

        with self.path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return AppConfig(**{**asdict(AppConfig()), **data})

    def save(self, config: AppConfig) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(asdict(config), handle, ensure_ascii=False, indent=2)
