"""Shared configuration helpers for Aurora voice input devices."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def get_voice_input_device_name(settings: Any, explicit_name: str | None = None) -> str:
    """Return one validated dshow device name for all Voice entry points."""

    value = explicit_name or _get_setting(settings, "voice.recorder.device_name", "")
    if not isinstance(value, str) or not value.strip():
        value = _get_setting(settings, "voice.recorder.last_successful_device_guid", "")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("voice.recorder.device_name must be selected or resolved")
    return value.strip()


def _get_setting(settings: Any, key: str, default: Any) -> Any:
    if isinstance(settings, Mapping):
        value: Any = settings
        for part in key.split("."):
            if not isinstance(value, Mapping) or part not in value:
                return default
            value = value[part]
        return value
    if hasattr(settings, "get"):
        return settings.get(key, default)
    return default
