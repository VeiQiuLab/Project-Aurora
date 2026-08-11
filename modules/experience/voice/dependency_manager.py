"""Voice dependency diagnostics and opt-in installer for Aurora."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

from modules.app_paths import find_bundled_tool
from modules.experience.subprocess_utils import with_hidden_console


@dataclass(frozen=True)
class VoiceDependency:
    """One dependency needed by the optional Voice Experience layer."""

    key: str
    name: str
    category: str
    import_name: str | None = None
    executable_setting: str | None = None
    executable_name: str | None = None
    pip_package: str | None = None
    installable: bool = True


VOICE_DEPENDENCIES = [
    VoiceDependency(
        key="faster_whisper",
        name="faster-whisper",
        category="STT",
        import_name="faster_whisper",
        pip_package="faster-whisper",
    ),
    VoiceDependency(
        key="whisper_runtime",
        name="whisper runtime",
        category="STT",
        import_name="ctranslate2",
        pip_package="ctranslate2",
    ),
    VoiceDependency(
        key="edge_tts",
        name="edge-tts",
        category="TTS",
        import_name="edge_tts",
        pip_package="edge-tts",
    ),
    VoiceDependency(
        key="sounddevice",
        name="sounddevice",
        category="Audio",
        import_name="sounddevice",
        pip_package="sounddevice",
    ),
    VoiceDependency(
        key="pygame",
        name="pygame",
        category="Audio",
        import_name="pygame",
        pip_package="pygame",
    ),
    VoiceDependency(
        key="ffmpeg",
        name="ffmpeg",
        category="FFmpeg",
        executable_setting="voice.recorder.ffmpeg_path",
        executable_name="ffmpeg",
        installable=False,
    ),
]


def check_dependencies(settings: Any = None) -> dict[str, Any]:
    """Return grouped Voice dependency diagnostics without importing providers."""

    items = []
    for dependency in VOICE_DEPENDENCIES:
        ready, detail = _dependency_ready(dependency, settings)
        items.append(
            {
                "key": dependency.key,
                "name": dependency.name,
                "category": dependency.category,
                "ready": ready,
                "detail": detail,
                "pip_package": dependency.pip_package,
                "installable": dependency.installable,
            }
        )

    missing = [item for item in items if not item["ready"]]
    categories = {}
    for item in items:
        category = item["category"]
        category_items = categories.setdefault(category, [])
        category_items.append(item)

    return {
        "ready": not missing,
        "items": items,
        "missing": missing,
        "categories": categories,
    }


def get_missing_dependencies(settings: Any = None) -> list[str]:
    """Return missing dependency names for logs and UI summaries."""

    return [item["name"] for item in check_dependencies(settings)["missing"]]


def install_dependencies(settings: Any = None) -> dict[str, Any]:
    """Install missing Python voice packages in the current Python environment."""

    report = check_dependencies(settings)
    if getattr(sys, "frozen", False):
        return {
            "success": report["ready"],
            "installed": [],
            "skipped": [item["name"] for item in report["missing"]],
            "stdout": "",
            "stderr": "Packaged Aurora cannot install Python packages at runtime. Rebuild the installer with Voice dependencies bundled.",
            "report": report,
        }
    packages = [
        item["pip_package"]
        for item in report["missing"]
        if item.get("installable") and item.get("pip_package")
    ]
    skipped = [
        item["name"]
        for item in report["missing"]
        if not item.get("installable")
    ]
    if not packages:
        return {
            "success": not skipped,
            "installed": [],
            "skipped": skipped,
            "stdout": "",
            "stderr": "No installable Python voice dependencies are missing.",
            "report": check_dependencies(settings),
        }

    command = [sys.executable, "-m", "pip", "install", *packages]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            **with_hidden_console(),
        )
    except Exception as error:
        return {
            "success": False,
            "installed": [],
            "skipped": skipped,
            "stdout": "",
            "stderr": str(error),
            "report": report,
        }

    refreshed = check_dependencies(settings)
    return {
        "success": completed.returncode == 0 and refreshed["ready"],
        "installed": packages,
        "skipped": skipped,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "returncode": completed.returncode,
        "report": refreshed,
    }


def _dependency_ready(dependency: VoiceDependency, settings: Any) -> tuple[bool, str]:
    if dependency.import_name:
        spec = importlib.util.find_spec(dependency.import_name)
        if spec is None:
            return False, "Not installed"
        return True, "Ready"

    executable = _get_setting(settings, dependency.executable_setting, "") if dependency.executable_setting else ""
    executable = str(executable or dependency.executable_name or "").strip()
    resolved = shutil.which(executable)
    if not resolved and dependency.executable_name:
        bundled = find_bundled_tool(dependency.executable_name)
        resolved = str(bundled) if bundled else None
    if resolved:
        return True, resolved
    return False, f"Executable not found: {executable or dependency.executable_name}"


def _get_setting(settings: Any, key: str | None, default: Any) -> Any:
    if not key:
        return default
    if isinstance(settings, dict):
        value: Any = settings
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value
    if hasattr(settings, "get"):
        return settings.get(key, default)
    return default
