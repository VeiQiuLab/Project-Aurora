"""Voice dependency diagnostics without runtime package installation."""

from __future__ import annotations

from typing import Any

from modules.runtime_dependencies import RuntimeDependencyManager


_COMPONENT_CATEGORIES = {
    "ffmpeg": "FFmpeg",
    "microphone": "Audio",
    "stt": "STT",
    "whisper_model": "STT",
    "tts": "TTS",
    "playback": "Audio",
}


def check_dependencies(settings: Any = None) -> dict[str, Any]:
    """Adapt the unified runtime report for the legacy setup contract."""

    unified = RuntimeDependencyManager(settings).check_voice_requirements()
    items = []
    for component in unified["items"]:
        key = str(component.get("key") or "")
        category = _COMPONENT_CATEGORIES.get(key, "Voice")
        ready = component.get("available") is True
        items.append(
            {
                "key": key,
                "name": str(component.get("name") or key),
                "category": category,
                "ready": ready,
                "detail": str(component.get("detail") or ""),
                "installable": False,
            }
        )

    missing = [item for item in items if not item["ready"]]
    categories = {}
    for item in items:
        categories.setdefault(item["category"], []).append(item)
    return {
        "ready": bool(unified["ready"]),
        "items": items,
        "missing": missing,
        "categories": categories,
        "runtime_report": unified,
    }


def get_missing_dependencies(settings: Any = None) -> list[str]:
    return [item["name"] for item in check_dependencies(settings)["missing"]]


def install_dependencies(settings: Any = None, *, confirmed: bool = False) -> dict[str, Any]:
    """Never modify Aurora's Python environment at runtime."""

    report = check_dependencies(settings)
    if not confirmed:
        return {
            "success": False,
            "confirmation_required": True,
            "installed": [],
            "skipped": [item["name"] for item in report["missing"]],
            "stdout": "",
            "stderr": "User confirmation is required before changing Voice components.",
            "report": report,
        }
    return {
        "success": bool(report["ready"]),
        "confirmation_required": False,
        "installed": [],
        "skipped": [item["name"] for item in report["missing"]],
        "stdout": "",
        "stderr": (
            "Aurora does not install Python packages at runtime. "
            "Use an official Aurora Full Build whose pinned Voice Runtime is included."
        ),
        "report": report,
    }
