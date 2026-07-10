from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .constants import LOG_ROOT, TASK_LOG_ROOT

APP_LOG_NAME = "qiuai_datamaker"


def setup_logging() -> logging.Logger:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(APP_LOG_NAME)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    file_handler = RotatingFileHandler(
        LOG_ROOT / "app.log",
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False
    return logger


def create_task_logger(task_name: str) -> tuple[logging.Logger, Path]:
    TASK_LOG_ROOT.mkdir(parents=True, exist_ok=True)
    log_path = TASK_LOG_ROOT / f"{task_name}.log"
    logger = logging.getLogger(f"{APP_LOG_NAME}.{task_name}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False
    return logger, log_path
