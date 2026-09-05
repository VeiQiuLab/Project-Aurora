"""Windows DirectShow audio-device discovery for the Voice Experience layer."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Callable

from modules.app_paths import find_bundled_tool
from modules.experience.subprocess_utils import with_hidden_console


class AudioDeviceDiscoveryError(RuntimeError):
    """Raised when FFmpeg cannot enumerate a usable audio input device."""


WINDOWS_DEFAULT_INPUT_ID = "windows-default-input"


@dataclass(frozen=True)
class DiscoveredAudioDevice:
    """One audio input with separate product-facing and backend identities."""

    name: str
    alternative_name: str
    backend_name: str = "DirectShow"
    is_default: bool = False

    @property
    def stable_id(self) -> str:
        return self.alternative_name or self.name

    @property
    def display_name(self) -> str:
        return friendly_device_name(self.name)

    @property
    def device_name(self) -> str:
        """Backward-compatible backend identifier used by FFmpeg."""

        return self.stable_id


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
    default_device = _match_windows_default_input(devices)
    if default_device is None:
        return devices
    return [
        DiscoveredAudioDevice(
            device.name,
            device.alternative_name,
            device.backend_name,
            device.stable_id == default_device.stable_id,
        )
        for device in devices
    ]


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
    configured_id = str(
        _get_setting(settings, "voice.recorder.device_id", "")
    ).strip()
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

    use_windows_default = configured_id == WINDOWS_DEFAULT_INPUT_ID or not any(
        (configured_id, configured_name, cached_guid, keyword)
    )
    if use_windows_default:
        default_match = _match_windows_default_input(devices)
        if default_match:
            return default_match.stable_id

    if configured_id and configured_id != WINDOWS_DEFAULT_INPUT_ID:
        configured_id_match = next(
            (device for device in devices if device.stable_id == configured_id),
            None,
        )
        if configured_id_match:
            return _cache_device(settings, configured_id_match)

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

    # A disconnected saved USB device must not make Voice crash. Resolve the
    # current Windows default for this run without overwriting the saved ID.
    default_match = _match_windows_default_input(devices)
    if default_match:
        return default_match.stable_id

    raise AudioDeviceDiscoveryError(
        "No usable dshow audio input device was resolved. Please select a microphone in Settings."
    )


def select_voice_input_device(
    settings: Any,
    device_id: str,
    *,
    display_name: str = "",
) -> str:
    """Persist a stable device ID while keeping the UI-facing name separate."""

    selected = str(device_id or "").strip()
    if not selected:
        raise ValueError("device_id must not be empty")
    _set_setting(settings, "voice.recorder.device_id", selected)
    _set_setting(settings, "voice.recorder.device_display_name", str(display_name or "").strip())
    if selected == WINDOWS_DEFAULT_INPUT_ID:
        _set_setting(settings, "voice.recorder.device_name", "")
        _set_setting(settings, "voice.recorder.last_successful_device_guid", "")
        return selected
    _set_setting(settings, "voice.recorder.device_name", selected)
    _set_setting(
        settings,
        "voice.recorder.last_successful_device_guid",
        selected if selected.startswith("@device_") else "",
    )
    return selected


def _cache_device(settings: Any, device: DiscoveredAudioDevice) -> str:
    resolved = device.device_name
    if device.alternative_name.startswith("@device_"):
        _set_setting(settings, "voice.recorder.last_successful_device_guid", resolved)
    return resolved


def _match_windows_default_input(devices: list[DiscoveredAudioDevice]) -> DiscoveredAudioDevice | None:
    marked = next((device for device in devices if device.is_default), None)
    if marked is not None:
        return marked
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


def friendly_device_name(value: str) -> str:
    """Return a safe human-readable fallback without exposing endpoint IDs."""

    text = str(value or "").strip().strip('"')
    text = re.sub(r"\s+\(audio\)\s*$", "", text, flags=re.IGNORECASE).strip()
    if not text or text.startswith("@device_") or re.search(r"\{[0-9A-F-]{20,}\}", text, re.IGNORECASE):
        return ""
    return text


def device_choice_map(
    devices: list[DiscoveredAudioDevice],
    *,
    default_label: str,
    fallback_label: str = "Microphone",
) -> dict[str, str]:
    """Map unique friendly labels to stable IDs for the microphone picker."""

    choices = {str(default_label): WINDOWS_DEFAULT_INPUT_ID}
    totals: dict[str, int] = {}
    for device in devices:
        base = device.display_name or fallback_label
        totals[base] = totals.get(base, 0) + 1
    seen: dict[str, int] = {}
    for device in devices:
        base = device.display_name or fallback_label
        seen[base] = seen.get(base, 0) + 1
        label = base if totals[base] == 1 else f"{base} · {seen[base]}"
        choices[label] = device.stable_id
    return choices


def _resolve_ffmpeg_path(ffmpeg_path: str) -> str:
    configured = str(ffmpeg_path or "ffmpeg").strip() or "ffmpeg"
    bundled = find_bundled_tool("ffmpeg")
    if bundled:
        return str(bundled)
    if configured.casefold() not in {"ffmpeg", "ffmpeg.exe"}:
        configured_path = Path(configured).expanduser()
        if configured_path.is_file():
            return str(configured_path)
        configured_command = shutil.which(configured)
        if configured_command:
            return configured_command
    return shutil.which("ffmpeg") or shutil.which("ffmpeg.exe") or configured


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
