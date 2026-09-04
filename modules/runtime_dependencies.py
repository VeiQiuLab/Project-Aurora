"""Read-only runtime and optional-dependency diagnostics for Aurora.

This module is the single backend contract used by first-run and dependency
screens.  It deliberately does not install packages, start services, download
models, open audio devices, or write settings.  Actions that change the host
must remain explicit UI/application operations performed after user consent.
"""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from modules.app_paths import PROGRAM_ROOT, find_bundled_tool
from modules.experience.subprocess_utils import with_hidden_console
from modules.models import infer_model_capability


DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"


class RuntimeStatus(str, Enum):
    """Stable statuses shared by first-run and dependency-center UIs."""

    READY = "Ready"
    MISSING = "Missing"
    OFFLINE = "Offline"
    OPTIONAL = "Optional"
    DEGRADED = "Degraded"


class OllamaRuntimeState(str, Enum):
    """The three user-relevant Ollama installation/service states."""

    NOT_INSTALLED = "Not Installed"
    INSTALLED_OFFLINE = "Installed / Server Offline"
    SERVER_READY = "Server Ready"


@dataclass(frozen=True)
class RuntimeItem:
    """One serializable runtime diagnostic."""

    key: str
    name: str
    status: RuntimeStatus
    detail: str
    required: bool = False
    available: bool | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "status": self.status.value,
            "detail": self.detail,
            "required": self.required,
            "available": self.available,
            "data": dict(self.data),
        }


MODEL_TIERS: dict[str, dict[str, Any]] = {
    "Lightweight": {
        "model": "qwen3:4b",
        "parameter_range": "3B/4B",
        "approximate_download_gb": 2.6,
    },
    "Balanced": {
        "model": "qwen3:8b",
        "parameter_range": "7B/8B",
        "approximate_download_gb": 5.2,
    },
    "Quality": {
        "model": "qwen3:14b",
        "parameter_range": "14B",
        "approximate_download_gb": 9.3,
    },
}


ApiProbe = Callable[[str, float], dict[str, Any]]
ModuleFinder = Callable[[str], Any]
AvailabilityProbe = Callable[[], tuple[bool | None, str]]
WhisperModelProbe = Callable[[str], tuple[bool | None, str]]
HardwareProbe = Callable[[], dict[str, Any]]


class RuntimeDependencyManager:
    """Collect runtime readiness without changing the user's machine.

    Every external probe is injectable so tests and callers can avoid touching
    real services or hardware.  The default probes are bounded, read-only
    inspections: an Ollama ``/api/tags`` request, module discovery, audio-device
    enumeration, disk usage, and (when installed) ``nvidia-smi`` inventory.
    """

    def __init__(
        self,
        settings: Any = None,
        *,
        which: Callable[[str], str | None] = shutil.which,
        bundled_tool_finder: Callable[[str], Path | None] = find_bundled_tool,
        module_finder: ModuleFinder = importlib.util.find_spec,
        ollama_api_probe: ApiProbe | None = None,
        microphone_probe: AvailabilityProbe | None = None,
        playback_device_probe: AvailabilityProbe | None = None,
        whisper_model_probe: WhisperModelProbe | None = None,
        hardware_probe: HardwareProbe | None = None,
        disk_path: str | os.PathLike[str] | None = None,
        environment: Mapping[str, str] | None = None,
    ):
        self.settings = settings if settings is not None else {}
        self._which = which
        self._find_bundled_tool = bundled_tool_finder
        self._find_module = module_finder
        self._ollama_api_probe = ollama_api_probe or self._probe_ollama_api
        self._microphone_probe = microphone_probe or self._probe_microphone
        self._playback_device_probe = playback_device_probe or self._probe_playback_device
        self._whisper_model_probe = whisper_model_probe or self._probe_whisper_model
        self._hardware_probe = hardware_probe
        self._disk_path = Path(disk_path) if disk_path is not None else PROGRAM_ROOT
        self._environment = os.environ if environment is None else environment

    def check(self, *, timeout: float = 1.0) -> dict[str, Any]:
        """Return the complete dependency report; probe failures never escape."""

        core = RuntimeItem(
            key="aurora_core",
            name="Aurora Core",
            status=RuntimeStatus.READY,
            detail="Aurora core runtime is available.",
            required=True,
            available=True,
        )
        ollama = self.check_ollama(timeout=timeout)
        ffmpeg = self.check_ffmpeg()
        voice = self.check_voice(ffmpeg=ffmpeg)
        hardware = self.inspect_hardware()
        recommendation = self.recommend_chat_model(
            hardware,
            ollama.get("models", {}).get("chat", []),
        )

        items = [
            core.as_dict(),
            ollama["executable"],
            ollama["service"],
            ollama["chat_model"],
            ollama["embedding_model"],
            ffmpeg,
            *voice["items"],
            voice["summary"],
        ]
        essential_ready = all(
            item["status"] == RuntimeStatus.READY.value
            for item in items
            if item.get("required")
        )
        return {
            "status": (
                RuntimeStatus.READY.value
                if essential_ready
                else RuntimeStatus.DEGRADED.value
            ),
            "core_ready": True,
            "items": items,
            "items_by_key": {item["key"]: item for item in items},
            "ollama": ollama,
            "voice": voice,
            "hardware": hardware,
            "recommendation": recommendation,
            "side_effects": [],
        }

    def check_ollama(self, *, timeout: float = 1.0) -> dict[str, Any]:
        """Report Ollama executable, API state, and classified local models."""

        command = str(
            _get_setting(self.settings, "services.ollama.command", "ollama serve")
            or "ollama serve"
        ).strip()
        executable_path, executable_source = self._resolve_ollama_executable(command)
        host = str(
            _get_setting(self.settings, "ollama.host", DEFAULT_OLLAMA_HOST)
            or DEFAULT_OLLAMA_HOST
        ).strip().rstrip("/")

        try:
            probe = self._ollama_api_probe(host, max(float(timeout), 0.05))
            if not isinstance(probe, Mapping):
                raise TypeError("Ollama API probe returned a non-mapping value")
        except Exception as error:
            probe = {
                "available": False,
                "reason": f"Probe failed: {type(error).__name__}: {error}",
                "models": [],
            }

        api_available = bool(probe.get("available"))
        models = classify_ollama_models(probe.get("models", [])) if api_available else {
            "all": [],
            "chat": [],
            "embedding": [],
        }
        executable_available = bool(executable_path)

        if api_available:
            runtime_state = OllamaRuntimeState.SERVER_READY
        elif executable_available:
            runtime_state = OllamaRuntimeState.INSTALLED_OFFLINE
        else:
            runtime_state = OllamaRuntimeState.NOT_INSTALLED

        executable_status = (
            RuntimeStatus.READY
            if executable_available
            else (RuntimeStatus.DEGRADED if api_available else RuntimeStatus.MISSING)
        )
        executable_detail = (
            f"Ollama executable found via {executable_source}: {executable_path}"
            if executable_available
            else (
                "Ollama API is ready, but a local Ollama executable was not found."
                if api_available
                else "Ollama executable was not found."
            )
        )
        service_status = RuntimeStatus.READY if api_available else RuntimeStatus.OFFLINE
        service_detail = (
            "Ollama API is available."
            if api_available
            else str(probe.get("reason") or "Ollama API is offline.")
        )

        configured_chat = str(_get_setting(self.settings, "chat_model", "") or "").strip()
        configured_embedding = str(
            _get_setting(self.settings, "embedding_model", "") or ""
        ).strip()
        chat_names = [item["name"] for item in models["chat"]]
        embedding_names = [item["name"] for item in models["embedding"]]
        selected_chat_available = _model_is_available(configured_chat, chat_names)
        selected_embedding_available = _model_is_available(
            configured_embedding, embedding_names
        )

        if chat_names:
            if selected_chat_available:
                chat_status = RuntimeStatus.READY
                chat_detail = f"Configured Chat model is available: {configured_chat}"
            elif configured_chat:
                chat_status = RuntimeStatus.DEGRADED
                chat_detail = f"Configured chat model is unavailable: {configured_chat}"
            else:
                chat_status = RuntimeStatus.DEGRADED
                chat_detail = "Chat-capable models are installed, but none is selected."
        elif api_available:
            chat_status = RuntimeStatus.MISSING
            chat_detail = "No chat-capable Ollama model is installed."
        else:
            chat_status = RuntimeStatus.OFFLINE
            chat_detail = "Chat models cannot be checked while the Ollama API is offline."

        if embedding_names:
            if selected_embedding_available:
                embedding_status = RuntimeStatus.READY
                embedding_detail = (
                    f"Configured embedding model is available: {configured_embedding}"
                )
            elif configured_embedding:
                embedding_status = RuntimeStatus.DEGRADED
                embedding_detail = (
                    f"Configured embedding model is unavailable: {configured_embedding}"
                )
            else:
                embedding_status = RuntimeStatus.OPTIONAL
                embedding_detail = "An embedding model is installed but not selected."
        else:
            embedding_status = RuntimeStatus.OPTIONAL
            embedding_detail = (
                "No embedding model is installed; semantic Knowledge search remains optional."
                if api_available
                else "Embedding models can be checked when the Ollama API is online."
            )

        executable_item = RuntimeItem(
            key="ollama",
            name="Ollama",
            status=executable_status,
            detail=executable_detail,
            required=True,
            available=executable_available,
            data={
                "path": executable_path,
                "source": executable_source,
                "runtime_state": runtime_state.value,
                "command": command,
            },
        ).as_dict()
        service_item = RuntimeItem(
            key="local_ai_service",
            name="Local AI Service",
            status=service_status,
            detail=service_detail,
            required=True,
            available=api_available,
            data={
                "host": host,
                "http_status": probe.get("http_status"),
                "runtime_state": runtime_state.value,
            },
        ).as_dict()
        chat_item = RuntimeItem(
            key="chat_model",
            name="Chat Model",
            status=chat_status,
            detail=chat_detail,
            required=True,
            available=bool(chat_names),
            data={
                "configured": configured_chat,
                "configured_available": selected_chat_available,
                "models": chat_names,
            },
        ).as_dict()
        embedding_item = RuntimeItem(
            key="embedding_model",
            name="Embedding",
            status=embedding_status,
            detail=embedding_detail,
            required=False,
            available=bool(embedding_names),
            data={
                "configured": configured_embedding,
                "configured_available": selected_embedding_available,
                "models": embedding_names,
                "recommended": "nomic-embed-text",
            },
        ).as_dict()

        return {
            "state": runtime_state.value,
            "available": api_available,
            "reason": service_detail,
            "host": host,
            "executable_path": executable_path,
            "executable_source": executable_source,
            "models": models,
            "executable": executable_item,
            "service": service_item,
            "chat_model": chat_item,
            "embedding_model": embedding_item,
        }

    def model_catalog(self, *, timeout: float = 1.0) -> dict[str, Any]:
        """Return the model-fetcher contract consumed by the existing wizard."""

        report = self.check_ollama(timeout=timeout)
        return {
            "ok": bool(report["available"]),
            "reason": report["reason"],
            "state": report["state"],
            "models": report["models"]["all"],
            "chat_models": report["models"]["chat"],
            "embedding_models": report["models"]["embedding"],
        }

    def check_ffmpeg(self) -> dict[str, Any]:
        """Resolve FFmpeg in the required bundled/configured/PATH order."""

        configured = str(
            _get_setting(self.settings, "voice.recorder.ffmpeg_path", "ffmpeg")
            or "ffmpeg"
        ).strip()
        path = ""
        source = ""
        try:
            bundled = self._find_bundled_tool("ffmpeg")
            if bundled and Path(bundled).is_file():
                path, source = str(Path(bundled)), "bundled"
            elif configured and configured.casefold() not in {"ffmpeg", "ffmpeg.exe"}:
                configured_path = Path(configured).expanduser()
                if configured_path.is_file():
                    path, source = str(configured_path), "configured"
                elif not configured_path.is_absolute() and configured_path.parent == Path("."):
                    resolved = self._which(configured)
                    if resolved:
                        path, source = str(resolved), "configured"
            if not path:
                resolved = self._which("ffmpeg") or self._which("ffmpeg.exe")
                if resolved:
                    path, source = str(resolved), "PATH"
        except Exception:
            path, source = "", ""

        return RuntimeItem(
            key="ffmpeg",
            name="FFmpeg",
            status=RuntimeStatus.READY if path else RuntimeStatus.MISSING,
            detail=(
                f"FFmpeg found via {source}: {path}"
                if path
                else "FFmpeg was not found; Voice recording is unavailable."
            ),
            required=False,
            available=bool(path),
            data={"path": path, "source": source, "configured": configured},
        ).as_dict()

    def check_voice(self, *, ffmpeg: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Check optional Voice components without loading models or devices."""

        voice_enabled = bool(_get_setting(self.settings, "voice.enabled", False))
        ffmpeg_item = dict(ffmpeg or self.check_ffmpeg())

        faster_whisper = self._module_available("faster_whisper")
        ctranslate2 = self._module_available("ctranslate2")
        stt_ready = faster_whisper and ctranslate2
        stt_detail = (
            "Faster-Whisper runtime is installed."
            if stt_ready
            else "Missing Faster-Whisper runtime: "
            + ", ".join(
                name
                for name, available in (
                    ("faster-whisper", faster_whisper),
                    ("ctranslate2", ctranslate2),
                )
                if not available
            )
        )

        model_size = str(
            _get_setting(self.settings, "voice.stt.model_size", "small") or "small"
        ).strip()
        if stt_ready:
            try:
                whisper_available, whisper_detail = self._whisper_model_probe(model_size)
            except Exception as error:
                whisper_available = None
                whisper_detail = f"Whisper model check failed: {type(error).__name__}: {error}"
        else:
            whisper_available = False
            whisper_detail = "Whisper model cannot be used until the STT runtime is installed."

        try:
            microphone_available, microphone_detail = self._microphone_probe()
        except Exception as error:
            microphone_available = None
            microphone_detail = f"Microphone check failed: {type(error).__name__}: {error}"

        edge_tts = self._module_available("edge_tts")
        tts_detail = (
            "Edge-TTS runtime is installed; online synthesis is checked when used."
            if edge_tts
            else "edge-tts is not installed."
        )

        pygame_available = self._module_available("pygame")
        if pygame_available:
            try:
                output_available, output_detail = self._playback_device_probe()
            except Exception as error:
                output_available = None
                output_detail = f"Playback device check failed: {type(error).__name__}: {error}"
        else:
            output_available = False
            output_detail = "pygame is not installed."

        component_values = {
            "ffmpeg": bool(ffmpeg_item.get("available")),
            "microphone": microphone_available,
            "stt": stt_ready,
            "whisper_model": whisper_available,
            "tts": edge_tts,
            "playback": output_available if pygame_available else False,
        }
        details = {
            "ffmpeg": str(ffmpeg_item.get("detail", "")),
            "microphone": microphone_detail,
            "stt": stt_detail,
            "whisper_model": whisper_detail,
            "tts": tts_detail,
            "playback": output_detail,
        }
        names = {
            "ffmpeg": "FFmpeg",
            "microphone": "Microphone",
            "stt": "STT",
            "whisper_model": "Whisper Model",
            "tts": "TTS",
            "playback": "Playback",
        }

        items = []
        for key in ("microphone", "stt", "whisper_model", "tts", "playback"):
            available = component_values[key]
            status = _optional_component_status(available, voice_enabled)
            items.append(
                RuntimeItem(
                    key=key,
                    name=names[key],
                    status=status,
                    detail=details[key],
                    required=False,
                    available=available,
                    data=(
                        {"model_size": model_size}
                        if key == "whisper_model"
                        else {}
                    ),
                ).as_dict()
            )

        all_ready = all(value is True for value in component_values.values())
        if not voice_enabled:
            summary_status = RuntimeStatus.OPTIONAL
            summary_detail = "Voice is disabled; missing Voice components do not affect Aurora Core."
        elif all_ready:
            summary_status = RuntimeStatus.READY
            summary_detail = "Voice dependencies are ready."
        else:
            summary_status = RuntimeStatus.DEGRADED
            unavailable = [
                names[key]
                for key, value in component_values.items()
                if value is not True
            ]
            summary_detail = "Voice is unavailable or degraded: " + ", ".join(unavailable)

        summary = RuntimeItem(
            key="voice",
            name="Voice",
            status=summary_status,
            detail=summary_detail,
            required=False,
            available=all_ready,
            data={"enabled": voice_enabled, "components": component_values},
        ).as_dict()
        return {
            "enabled": voice_enabled,
            "ready": all_ready,
            "status": summary_status.value,
            "items": items,
            "summary": summary,
            "components": component_values,
        }

    def check_voice_requirements(self) -> dict[str, Any]:
        """Return the unified Voice startup gate used by production callers."""

        ffmpeg = self.check_ffmpeg()
        voice = self.check_voice(ffmpeg=ffmpeg)
        items = [ffmpeg, *voice["items"]]
        missing = [item for item in items if item.get("available") is not True]
        return {
            "ready": bool(voice["ready"]),
            "items": items,
            "missing": missing,
            "voice": voice,
        }

    def inspect_hardware(self) -> dict[str, Any]:
        """Return conservative hardware facts; unknown VRAM remains ``None``."""

        if self._hardware_probe is not None:
            try:
                hardware = dict(self._hardware_probe() or {})
            except Exception as error:
                hardware = {"warnings": [f"Hardware probe failed: {type(error).__name__}: {error}"]}
        else:
            hardware = self._default_hardware_probe()

        hardware.setdefault("ram_gb", None)
        hardware.setdefault("cpu", platform.processor() or platform.machine() or "unknown")
        hardware.setdefault("logical_cores", os.cpu_count())
        hardware.setdefault("gpu", None)
        hardware.setdefault("vram_gb", None)
        hardware.setdefault("disk_free_gb", None)
        hardware.setdefault("warnings", [])
        if not isinstance(hardware.get("warnings"), list):
            hardware["warnings"] = [str(hardware["warnings"])]
        if hardware.get("vram_gb") is None:
            hardware["vram_status"] = "unknown"
        else:
            hardware["vram_status"] = "known"
        return hardware

    def recommend_chat_model(
        self,
        hardware: Mapping[str, Any],
        existing_chat_models: Iterable[Mapping[str, Any] | str] = (),
    ) -> dict[str, Any]:
        """Recommend a coarse model tier without downloading anything."""

        ram = _positive_float_or_none(hardware.get("ram_gb"))
        vram = _positive_float_or_none(hardware.get("vram_gb"))
        disk = _positive_float_or_none(hardware.get("disk_free_gb"))
        cores = _positive_int_or_none(hardware.get("logical_cores"))

        warnings: list[str] = []
        if vram is None:
            warnings.append("VRAM could not be measured reliably and was not treated as 0.")
        if ram is None:
            warnings.append("RAM could not be measured; using the conservative tier.")
        if disk is not None and disk < 6.0:
            warnings.append("Free disk space is low; free space before downloading a model.")

        if (
            ram is not None
            and ram >= 32.0
            and vram is not None
            and vram >= 12.0
            and (cores is None or cores >= 8)
            and (disk is None or disk >= 15.0)
        ):
            tier = "Quality"
            reason = "High RAM and confirmed VRAM support a 14B quality model."
        elif (
            ram is not None
            and ram >= 16.0
            and (cores is None or cores >= 4)
            and (disk is None or disk >= 8.0)
        ):
            tier = "Balanced"
            reason = "Mainstream hardware is suited to a 7B/8B balanced model."
        else:
            tier = "Lightweight"
            reason = "A 3B/4B model is the safest fit for limited or unknown hardware."

        tier_data = dict(MODEL_TIERS[tier])
        existing = _select_existing_chat_model(existing_chat_models, tier)
        if existing:
            model = existing["name"]
            action = "use_existing"
            download_required = False
            reason = f"Use the existing chat-capable model {model}; no download is needed."
        else:
            model = tier_data["model"]
            action = "download_recommended"
            download_required = True

        approximate_download = float(tier_data["approximate_download_gb"])
        can_download = disk is None or disk >= approximate_download + 2.0
        if download_required and not can_download:
            warnings.append(
                "The recommended download plus safety margin may not fit on the current disk."
            )

        return {
            "tier": tier,
            "model": model,
            "parameter_range": tier_data["parameter_range"],
            "approximate_download_gb": approximate_download,
            "reason": reason,
            "action": action,
            "existing_model": bool(existing),
            "download_required": download_required,
            "can_download": can_download,
            "warnings": warnings,
            "requires_user_confirmation": download_required,
        }

    def _resolve_ollama_executable(self, command: str) -> tuple[str, str]:
        return resolve_ollama_executable(
            command,
            which=self._which,
            bundled_tool_finder=self._find_bundled_tool,
            environment=self._environment,
        )

    def _module_available(self, name: str) -> bool:
        try:
            return self._find_module(name) is not None
        except Exception:
            return False

    def _probe_microphone(self) -> tuple[bool | None, str]:
        if not self._module_available("sounddevice"):
            return False, "sounddevice is not installed."
        try:
            import sounddevice

            device = sounddevice.query_devices(kind="input")
        except Exception as error:
            return False, f"No usable microphone was detected: {error}"
        name = str(device.get("name", "") or "").strip() if isinstance(device, Mapping) else ""
        if not name:
            return False, "No usable microphone was detected."
        return True, f"Microphone detected: {name}"

    def _probe_playback_device(self) -> tuple[bool | None, str]:
        # Device enumeration is read-only.  Do not initialize pygame.mixer here.
        if not self._module_available("sounddevice"):
            return None, "pygame is installed; an output device will be verified when Voice is used."
        try:
            import sounddevice

            device = sounddevice.query_devices(kind="output")
        except Exception as error:
            return None, f"pygame is installed, but output availability is unconfirmed: {error}"
        name = str(device.get("name", "") or "").strip() if isinstance(device, Mapping) else ""
        if not name:
            return False, "No usable audio output device was detected."
        return True, f"Playback device detected: {name}"

    def _probe_whisper_model(self, model_size: str) -> tuple[bool | None, str]:
        configured = Path(model_size).expanduser()
        if configured.exists():
            return True, f"Whisper model path is available: {configured}"

        cache_root = os.environ.get("HF_HUB_CACHE")
        if cache_root:
            hub = Path(cache_root)
        else:
            hf_home = os.environ.get("HF_HOME")
            hub = Path(hf_home) / "hub" if hf_home else Path.home() / ".cache" / "huggingface" / "hub"
        normalized = model_size.strip().casefold().replace("_", "-")
        repository = hub / f"models--Systran--faster-whisper-{normalized}"
        snapshots = repository / "snapshots"
        if snapshots.is_dir():
            try:
                if any(path.is_dir() for path in snapshots.iterdir()):
                    return True, f"Whisper model cache is available: {model_size}"
            except OSError:
                return None, f"Whisper model cache could not be inspected: {model_size}"
        return False, f"Whisper model is not cached locally: {model_size}"

    def _default_hardware_probe(self) -> dict[str, Any]:
        warnings: list[str] = []
        ram_gb = None
        try:
            import psutil

            ram_gb = round(float(psutil.virtual_memory().total) / (1024 ** 3), 1)
        except Exception as error:
            warnings.append(f"RAM unavailable: {type(error).__name__}")

        disk_free_gb = None
        try:
            disk_free_gb = round(float(shutil.disk_usage(self._disk_path).free) / (1024 ** 3), 1)
        except Exception as error:
            warnings.append(f"Disk availability unavailable: {type(error).__name__}")

        gpu_name = None
        vram_gb = None
        try:
            nvidia_smi = self._which("nvidia-smi")
            if nvidia_smi:
                result = subprocess.run(
                    [
                        nvidia_smi,
                        "--query-gpu=name,memory.total",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=3,
                    check=False,
                    **with_hidden_console(),
                )
                if result.returncode == 0:
                    rows = [row.strip() for row in result.stdout.splitlines() if row.strip()]
                    parsed = []
                    for row in rows:
                        name, separator, memory = row.rpartition(",")
                        if separator:
                            parsed.append((name.strip(), float(memory.strip()) / 1024.0))
                    if parsed:
                        gpu_name, vram_gb = max(parsed, key=lambda item: item[1])
                        vram_gb = round(vram_gb, 1)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            warnings.append(f"GPU inventory unavailable: {type(error).__name__}")

        return {
            "ram_gb": ram_gb,
            "cpu": platform.processor() or platform.machine() or "unknown",
            "logical_cores": os.cpu_count(),
            "gpu": gpu_name,
            "vram_gb": vram_gb,
            "disk_free_gb": disk_free_gb,
            "warnings": warnings,
        }

    @staticmethod
    def _probe_ollama_api(host: str, timeout: float) -> dict[str, Any]:
        target = str(host or DEFAULT_OLLAMA_HOST).rstrip("/") + "/api/tags"
        try:
            with urllib.request.urlopen(target, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, Mapping):
                    raise ValueError("Ollama returned a non-object response")
                models = payload.get("models", [])
                if not isinstance(models, list):
                    raise ValueError("Ollama returned an invalid model list")
                return {
                    "available": True,
                    "reason": "API available",
                    "http_status": int(getattr(response, "status", 200)),
                    "models": models,
                }
        except urllib.error.HTTPError as error:
            return {
                "available": False,
                "reason": f"HTTP {error.code}",
                "http_status": int(error.code),
                "models": [],
            }
        except (urllib.error.URLError, OSError, TimeoutError, ValueError, json.JSONDecodeError) as error:
            reason = getattr(error, "reason", error)
            return {"available": False, "reason": str(reason), "models": []}


def check_runtime_dependencies(
    settings: Any = None,
    *,
    timeout: float = 1.0,
) -> dict[str, Any]:
    """Convenience entry point for callers that do not need injected probes."""

    return RuntimeDependencyManager(settings).check(timeout=timeout)


def resolve_ollama_executable(
    command: str = "ollama serve",
    *,
    which: Callable[[str], str | None] = shutil.which,
    bundled_tool_finder: Callable[[str], Path | None] = find_bundled_tool,
    environment: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Resolve Ollama even when an installer changed PATH after Aurora started."""

    try:
        parts = shlex.split(str(command or ""), posix=False)
        candidate = str(parts[0] if parts else "").strip().strip('"')
    except (TypeError, ValueError):
        candidate = ""

    if candidate:
        candidate_path = Path(candidate).expanduser()
        if candidate_path.is_file():
            return str(candidate_path.resolve()), "configured"

    try:
        bundled = bundled_tool_finder("ollama")
        if bundled and Path(bundled).is_file():
            return str(Path(bundled).resolve()), "bundled"
    except Exception:
        pass

    try:
        lookup = candidate or "ollama"
        resolved = which(lookup) or which("ollama") or which("ollama.exe")
        if resolved:
            return str(Path(resolved)), "PATH"
    except Exception:
        pass

    env = os.environ if environment is None else environment
    known_locations: list[tuple[str, Path]] = []
    local_app_data = str(env.get("LOCALAPPDATA", "") or "").strip()
    if local_app_data:
        known_locations.append(
            ("Ollama Windows install", Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe")
        )
    program_files = str(env.get("ProgramFiles", "") or "").strip()
    if program_files:
        known_locations.append(
            ("Ollama Windows install", Path(program_files) / "Ollama" / "ollama.exe")
        )
    for source, path in known_locations:
        try:
            if path.is_file():
                return str(path.resolve()), source
        except OSError:
            continue
    return "", ""


def classify_ollama_models(models: Iterable[Mapping[str, Any] | str]) -> dict[str, list[dict[str, Any]]]:
    """Normalize Ollama records and separate chat from embedding-only models."""

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in models or ():
        if isinstance(raw, Mapping):
            name = str(raw.get("name") or raw.get("model") or "").strip()
            if not name:
                continue
            record = {
                "name": name,
                "model_id": str(raw.get("digest") or raw.get("model_id") or ""),
                "size": raw.get("size", ""),
                "modified": str(raw.get("modified_at") or raw.get("modified") or ""),
            }
            details = raw.get("details")
            if isinstance(details, Mapping):
                record["details"] = dict(details)
        else:
            name = str(raw or "").strip()
            if not name:
                continue
            record = {"name": name, "model_id": "", "size": "", "modified": ""}
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        capability = infer_model_capability(name)
        record["capability"] = capability
        record["chat_supported"] = capability == "Chat Supported"
        records.append(record)
    return {
        "all": records,
        "chat": [item for item in records if item["chat_supported"]],
        "embedding": [item for item in records if not item["chat_supported"]],
    }


def _get_setting(settings: Any, key: str, default: Any) -> Any:
    if isinstance(settings, Mapping):
        value: Any = settings
        for part in key.split("."):
            if not isinstance(value, Mapping) or part not in value:
                return default
            value = value[part]
        return value
    if hasattr(settings, "get"):
        try:
            return settings.get(key, default)
        except Exception:
            return default
    return default


def _optional_component_status(
    available: bool | None,
    voice_enabled: bool,
) -> RuntimeStatus:
    if available is True:
        return RuntimeStatus.READY
    if not voice_enabled:
        return RuntimeStatus.OPTIONAL
    if available is None:
        return RuntimeStatus.DEGRADED
    return RuntimeStatus.MISSING


def _model_key(name: str) -> str:
    normalized = str(name or "").strip().casefold()
    tail = normalized.rsplit("/", 1)[-1]
    return normalized[:-7] if normalized.endswith(":latest") and tail.count(":") == 1 else normalized


def _model_is_available(configured: str, available_names: Iterable[str]) -> bool:
    if not configured:
        return False
    target = _model_key(configured)
    return any(_model_key(name) == target for name in available_names)


def _positive_float_or_none(value: Any) -> float | None:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if converted > 0 else None


def _positive_int_or_none(value: Any) -> int | None:
    try:
        converted = int(value)
    except (TypeError, ValueError):
        return None
    return converted if converted > 0 else None


def _model_parameter_billions(model: Mapping[str, Any]) -> float | None:
    details = model.get("details")
    if isinstance(details, Mapping):
        parameter_size = str(details.get("parameter_size") or "")
        match = re.search(r"(\d+(?:\.\d+)?)\s*[bB]", parameter_size)
        if match:
            return float(match.group(1))
    name = str(model.get("name") or "")
    match = re.search(r"(?:^|[:_\-])(\d+(?:\.\d+)?)b(?:$|[_\-])", name, re.IGNORECASE)
    return float(match.group(1)) if match else None


def _select_existing_chat_model(
    models: Iterable[Mapping[str, Any] | str],
    tier: str,
) -> dict[str, Any] | None:
    classified = classify_ollama_models(models)["chat"]
    if not classified:
        return None
    target = {"Lightweight": 4.0, "Balanced": 8.0, "Quality": 14.0}[tier]

    def rank(model: Mapping[str, Any]) -> tuple[int, float, str]:
        parameters = _model_parameter_billions(model)
        if parameters is None:
            return (1, float("inf"), str(model.get("name", "")).casefold())
        return (0, abs(parameters - target), str(model.get("name", "")).casefold())

    return dict(min(classified, key=rank))


__all__ = [
    "DEFAULT_OLLAMA_HOST",
    "MODEL_TIERS",
    "OllamaRuntimeState",
    "RuntimeDependencyManager",
    "RuntimeItem",
    "RuntimeStatus",
    "check_runtime_dependencies",
    "classify_ollama_models",
    "resolve_ollama_executable",
]
