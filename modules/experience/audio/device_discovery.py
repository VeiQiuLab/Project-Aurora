"""Windows DirectShow audio-device discovery for the Voice Experience layer."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
import re
import subprocess
from typing import Any, Callable

from modules.app_paths import find_bundled_tool
from modules.experience.subprocess_utils import with_hidden_console


class AudioDeviceDiscoveryError(RuntimeError):
    """Raised when FFmpeg cannot enumerate a usable audio input device."""


@dataclass(frozen=True)
class DiscoveredAudioDevice:
    """A dshow audio device and its stable alternative-name identifier."""

    name: str
    alternative_name: str

    @property
    def device_name(self) -> str:
        return self.alternative_name or self.name


_AUDIO_DEVICE_RE = re.compile(r'"(?P<name>.+)"\s+\(audio\)\s*$')
_QUOTED_VALUE_RE = re.compile(r'"(?P<value>[^"]+)"')


def enumerate_dshow_audio_devices(
    ffmpeg_path: str = "ffmpeg",
    *,
    timeout_seconds: float = 10.0,
    run: Callable[..., Any] = subprocess.run,
) -> list[DiscoveredAudioDevice]:
    """Enumerate DirectShow audio devices using FFmpeg's stderr listing."""

    command = [
        _resolve_ffmpeg_path(ffmpeg_path),
        "-hide_banner",
        "-list_devices",
        "true",
        "-f",
        "dshow",
        "-i",
        "dummy",
    ]
    try:
        result = run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            **with_hidden_console(),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise AudioDeviceDiscoveryError(
            f"FFmpeg dshow enumeration failed: {error}"
        ) from error

    output = "\n".join(
        part for part in (result.stdout or "", result.stderr or "") if part
    )
    devices: list[DiscoveredAudioDevice] = []
    pending_name: str | None = None
    for line in output.splitlines():
        device_match = _AUDIO_DEVICE_RE.search(line)
        if device_match:
            if pending_name:
                devices.append(DiscoveredAudioDevice(pending_name, pending_name))
            pending_name = device_match.group("name").strip()
            continue
        if pending_name and "Alternative name" in line:
            alternative_match = _QUOTED_VALUE_RE.search(line)
            if alternative_match:
                devices.append(
                    DiscoveredAudioDevice(
                        pending_name,
                        alternative_match.group("value").strip(),
                    )
                )
                pending_name = None
    if pending_name:
        devices.append(DiscoveredAudioDevice(pending_name, pending_name))

    if not devices:
        raise AudioDeviceDiscoveryError(
            f"FFmpeg returned no dshow audio devices (return_code={result.returncode})"
        )
    return devices


def resolve_ffmpeg_path(ffmpeg_path: str = "ffmpeg") -> str:
    """Return a configured, PATH, or bundled FFmpeg executable path."""

    return _resolve_ffmpeg_path(ffmpeg_path)


def resolve_voice_input_device(
    settings: Any,
    explicit_name: str | None = None,
    *,
    run: Callable[..., Any] = subprocess.run,
) -> str:
    """Resolve the current Voice input identifier and cache successful GUIDs."""

    if explicit_name and explicit_name.strip():
        return explicit_name.strip()

    ffmpeg_path = str(_get_setting(settings, "voice.recorder.ffmpeg_path", "ffmpeg"))
    configured_name = str(_get_setting(settings, "voice.recorder.device_name", "")).strip()
    cached_guid = str(
        _get_setting(settings, "voice.recorder.last_successful_device_guid", "")
    ).strip()
    keyword = str(
        _get_setting(settings, "voice.recorder.preferred_device_keyword", "")
    ).strip().casefold()

    try:
        devices = enumerate_dshow_audio_devices(ffmpeg_path, run=run)
    except AudioDeviceDiscoveryError:
        if configured_name:
            return configured_name
        if cached_guid:
            return cached_guid
        raise

    if configured_name:
        configured_match = next(
            (
                device
                for device in devices
                if configured_name in {device.name, device.alternative_name}
            ),
            None,
        )
        if configured_match:
            return _cache_device(settings, configured_match)

    if cached_guid:
        cached_match = next(
            (device for device in devices if device.alternative_name == cached_guid),
            None,
        )
        if cached_match:
            return _cache_device(settings, cached_match)

    default_match = _match_windows_default_input(devices)
    if default_match:
        return _cache_device(settings, default_match)

    if keyword:
        keyword_match = next(
            (
                device
                for device in devices
                if keyword in device.name.casefold()
                or keyword in device.alternative_name.casefold()
            ),
            None,
        )
        if keyword_match:
            return _cache_device(settings, keyword_match)

    raise AudioDeviceDiscoveryError(
        "No usable dshow audio input device was resolved. Please select a microphone in Settings."
    )


def select_voice_input_device(settings: Any, device_name: str) -> str:
    """Persist a user-selected microphone while keeping cached GUID compatibility."""

    selected = str(device_name or "").strip()
    if not selected:
        raise ValueError("device_name must not be empty")
    _set_setting(settings, "voice.recorder.device_name", selected)
    _set_setting(settings, "voice.recorder.last_successful_device_guid", "")
    return selected


def _cache_device(settings: Any, device: DiscoveredAudioDevice) -> str:
    resolved = device.device_name
    if device.alternative_name.startswith("@device_"):
        _set_setting(settings, "voice.recorder.last_successful_device_guid", resolved)
    return resolved


def _match_windows_default_input(devices: list[DiscoveredAudioDevice]) -> DiscoveredAudioDevice | None:
    default_name = _windows_default_input_name()
    if not default_name:
        return devices[0] if devices else None
    default_key = default_name.casefold()
    return next(
        (
            device
            for device in devices
            if default_key in device.name.casefold()
            or device.name.casefold() in default_key
        ),
        devices[0] if devices else None,
    )


def _windows_default_input_name() -> str:
    try:
        import sounddevice
    except Exception:
        return ""
    try:
        device = sounddevice.query_devices(kind="input")
    except Exception:
        return ""
    if not isinstance(device, dict):
        return ""
    return str(device.get("name", "") or "").strip()


def _resolve_ffmpeg_path(ffmpeg_path: str) -> str:
    configured = str(ffmpeg_path or "ffmpeg").strip() or "ffmpeg"
    if configured != "ffmpeg":
        return configured
    bundled = find_bundled_tool("ffmpeg")
    return str(bundled) if bundled else configured


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


def _set_setting(settings: Any, key: str, value: Any) -> None:
    if hasattr(settings, "set"):
        settings.set(key, value)
        return
    if not isinstance(settings, dict):
        return
    target = settings
    parts = key.split(".")
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value
