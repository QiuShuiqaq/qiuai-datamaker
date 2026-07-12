from __future__ import annotations

from pathlib import Path

from .runtime import get_app_root, get_data_root, get_project_root, get_resource_root

APP_NAME = "QiuAi Datamaker"

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = get_project_root()
APP_ROOT = get_app_root()
RESOURCE_ROOT = get_resource_root()
DATA_ROOT = get_data_root(APP_NAME.replace(" ", ""))
LOG_ROOT = DATA_ROOT / "logs"
TASK_LOG_ROOT = LOG_ROOT / "tasks"
WORK_ROOT = DATA_ROOT / "work"
RAW_IMPORT_ROOT = DATA_ROOT / "raw_imports"
SUBMISSION_ROOT = DATA_ROOT / "submissions"
EXPORT_ROOT = DATA_ROOT / "exports"
CONFIG_PATH = DATA_ROOT / "config.json"
DB_PATH = DATA_ROOT / "app.db"
LICENSE_PATH = DATA_ROOT / "activation.json"

SCRIPT_ROOT = RESOURCE_ROOT / "trajectory_scripts"

OPENCLAW_AGENT = "openclaw"
HERMES_AGENT = "hermes"

AGENT_LABELS = {
    OPENCLAW_AGENT: "OpenClaw",
    HERMES_AGENT: "Hermes",
}

PROCESS_STATUS_NEW = "new"
PROCESS_STATUS_READY = "ready"
PROCESS_STATUS_EXCLUDED = "excluded"
PROCESS_STATUS_PROCESSING = "processing"
PROCESS_STATUS_PASS = "pass"
PROCESS_STATUS_FAIL = "fail"
PROCESS_STATUS_ERROR = "error"

SCENES = [
    ("development", "Development"),
    ("system_admin", "System Admin"),
    ("data_analysis", "Data Analysis"),
    ("research", "Research"),
    ("content_creation", "Content Creation"),
    ("communication", "Communication"),
    ("media_processing", "Media Processing"),
    ("automation", "Automation"),
    ("monitoring", "Monitoring"),
    ("scheduling", "Scheduling"),
    ("knowledge_mgmt", "Knowledge Mgmt"),
    ("finance", "Finance"),
    ("crm", "CRM"),
]

SCENE_LABELS = dict(SCENES)

TARGET_AGENT_RATIO = {
    OPENCLAW_AGENT: 0.6,
    HERMES_AGENT: 0.4,
}

TARGET_MODEL_RATIO = {
    "claude-opus-4-8": 0.7,
    "claude-opus-4-6": 0.3,
}

SUPPORTED_MODELS = {"claude-opus-4-6", "claude-opus-4-8"}

WINDOW_MIN_WIDTH = 1200
WINDOW_MIN_HEIGHT = 760
