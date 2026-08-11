"""Filesystem locations for packaged and local Aurora runtime data."""

from __future__ import annotations

import os
import sys
from pathlib import Path


APP_DIR_NAME = "Aurora"


def program_root() -> Path:
    """Return the installed program root or source checkout root."""

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def user_data_dir() -> Path:
    """Return Aurora's per-user writable data directory."""

    override = os.environ.get("AURORA_USER_DATA_DIR")
    if override:
        return Path(override).expanduser()
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_DIR_NAME
    return Path.home() / "AppData" / "Roaming" / APP_DIR_NAME


PROGRAM_ROOT = program_root()
INTERNAL_ROOT = Path(getattr(sys, "_MEIPASS", PROGRAM_ROOT))
USER_DATA_DIR = user_data_dir()
CONFIG_DIR = USER_DATA_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "settings.json"
DEFAULT_SETTINGS_CANDIDATES = (
    PROGRAM_ROOT / "config" / "default_settings.json",
    INTERNAL_ROOT / "config" / "default_settings.json",
)
DEFAULT_SETTINGS_FILE = next(
    (path for path in DEFAULT_SETTINGS_CANDIDATES if path.is_file()),
    DEFAULT_SETTINGS_CANDIDATES[0],
)
CONVERSATIONS_DIR = USER_DATA_DIR / "conversations"
MEMORY_DIR = USER_DATA_DIR / "memory"
KNOWLEDGE_DIR = USER_DATA_DIR / "knowledge"
PERSONA_DIR = USER_DATA_DIR / "persona"
LOG_DIR = USER_DATA_DIR / "logs"
TOOLS_DIRS = (
    PROGRAM_ROOT / "tools",
    INTERNAL_ROOT / "tools",
    PROGRAM_ROOT / "_internal" / "tools",
)


def ensure_user_data_directories() -> None:
    for path in (
        USER_DATA_DIR,
        CONFIG_DIR,
        CONVERSATIONS_DIR,
        MEMORY_DIR,
        KNOWLEDGE_DIR,
        PERSONA_DIR,
        LOG_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def resolve_user_data_path(value: str | os.PathLike[str], *, base: Path = USER_DATA_DIR) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return base / path


def find_bundled_tool(name: str) -> Path | None:
    executable = f"{name}.exe" if os.name == "nt" and not name.lower().endswith(".exe") else name
    for directory in TOOLS_DIRS:
        candidate = directory / executable
        if candidate.is_file():
            return candidate
    return None
