"""Voice dependency diagnostics and opt-in installer for Aurora."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

from modules.experience.subprocess_utils import with_hidden_console
from modules.runtime_dependencies import RuntimeDependencyManager


_INSTALL_METADATA = {
    "ffmpeg": ("FFmpeg", None),
    "microphone": ("Audio", None),
    "stt": ("STT", "faster-whisper"),
    "whisper_model": ("STT", None),
    "tts": ("TTS", "edge-tts"),
    "playback": ("Audio", "pygame"),
}


def check_dependencies(settings: Any = None) -> dict[str, Any]:
    """Adapt the unified runtime report for the legacy installer contract."""

    unified = RuntimeDependencyManager(settings).check_voice_requirements()
    items = []
    for component in unified["items"]:
        key = str(component.get("key") or "")
        category, pip_package = _INSTALL_METADATA.get(key, ("Voice", None))
        ready = component.get("available") is True
        items.append(
            {
                "key": key,
                "name": str(component.get("name") or key),
                "category": category,
                "ready": ready,
                "detail": str(component.get("detail") or ""),
                "pip_package": pip_package,
                "installable": bool(pip_package),
            }
        )

    missing = [item for item in items if not item["ready"]]
    categories = {}
    for item in items:
        category = item["category"]
        category_items = categories.setdefault(category, [])
        category_items.append(item)

    return {
        "ready": bool(unified["ready"]),
        "items": items,
        "missing": missing,
        "categories": categories,
        "runtime_report": unified,
    }


def get_missing_dependencies(settings: Any = None) -> list[str]:
    """Return missing dependency names for logs and UI summaries."""

    return [item["name"] for item in check_dependencies(settings)["missing"]]


def install_dependencies(settings: Any = None, *, confirmed: bool = False) -> dict[str, Any]:
    """Install missing Python packages only after explicit user confirmation."""

    report = check_dependencies(settings)
    if not confirmed:
        return {
            "success": False,
            "confirmation_required": True,
            "installed": [],
            "skipped": [item["name"] for item in report["missing"]],
            "stdout": "",
            "stderr": "User confirmation is required before installing Voice packages.",
            "report": report,
        }
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
