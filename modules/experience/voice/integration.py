"""Application composition for the optional full Voice Experience pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from threading import Event
from typing import Any

from modules.diagnostics import create_diagnostics
from modules.experience.audio.device_discovery import (
    AudioDeviceDiscoveryError,
    resolve_ffmpeg_path,
    resolve_voice_input_device,
)
from modules.experience.audio.playback import AudioPlaybackController
from modules.experience.audio.recorder import AudioRecorder
from modules.experience.audio.real_playback import RealPlaybackController
from modules.experience.audio.ffmpeg_source import FFmpegAudioFrameSource
from modules.experience.audio.frame_pipeline import AudioFrameBuffer
from modules.experience.audio.vad import RMSVADAdapter
from modules.experience.state import CompanionStateStore
from modules.runtime_dependencies import RuntimeDependencyManager

from .fake import FakeSpeechToTextProvider, FakeTextToSpeechProvider
from .interfaces import SpeechToTextProvider, TextToSpeechProvider
from .orchestrator import VoiceOrchestrator
from .session import VoiceSessionManager
from .providers.edge_tts import EdgeTTSProvider
from .providers.faster_whisper import FasterWhisperProvider
from .runtime import RuntimeService, StateCallback


def create_optional_voice_runtime(
    settings: Any,
    runtime_factory,
    *,
    dependency_checker=None,
) -> tuple[RuntimeService | None, dict[str, Any]]:
    """Create optional Voice safely without making it a Core startup dependency."""

    if not _get_setting(settings, "voice.enabled", False):
        return None, create_diagnostics(
            stage="voice.startup",
            success=True,
            reason="disabled",
            metrics={"enabled": False, "runtime_available": False},
        )

    dependency_checker = dependency_checker or (
        lambda current_settings: RuntimeDependencyManager(
            current_settings
        ).check_voice_requirements()
    )
    try:
        dependency_report = dependency_checker(settings)
    except Exception as error:
        return None, create_diagnostics(
            stage="voice.startup",
            success=False,
            reason="dependency_check_failed",
            warnings=[
                "Voice dependencies could not be checked. Aurora Core will continue; "
                "open Runtime / Dependencies and try again."
            ],
            metrics={"enabled": True, "runtime_available": False},
            trace={"exception_type": type(error).__name__},
        )

    if not isinstance(dependency_report, Mapping):
        return None, create_diagnostics(
            stage="voice.startup",
            success=False,
            reason="dependency_check_failed",
            warnings=["Voice dependency check returned an invalid result."],
            metrics={"enabled": True, "runtime_available": False},
        )

    missing = dependency_report.get("missing", [])
    if not dependency_report.get("ready", False) or missing:
        missing_names = [
            str(item.get("name", item.get("key", "unknown")))
            for item in missing
            if isinstance(item, Mapping)
        ]
        missing_names = missing_names or ["unknown"]
        return None, create_diagnostics(
            stage="voice.startup",
            success=False,
            reason="dependency_missing",
            warnings=[
                "Voice is unavailable because required components are missing: "
                + ", ".join(missing_names)
            ],
            metrics={
                "enabled": True,
                "runtime_available": False,
                "missing_dependencies": missing_names,
            },
        )

    try:
        runtime = runtime_factory()
    except AudioDeviceDiscoveryError as error:
        return None, create_diagnostics(
            stage="voice.startup",
            success=False,
            reason="audio_device_unavailable",
            warnings=[
                "Voice is unavailable because Aurora could not access a usable microphone. "
                "Check FFmpeg, Windows microphone permission, and the selected input device."
            ],
            metrics={"enabled": True, "runtime_available": False},
            trace={"exception_type": type(error).__name__},
        )
    except Exception as error:
        return None, create_diagnostics(
            stage="voice.startup",
            success=False,
            reason="initialization_failed",
            warnings=[
                "Voice could not start. Aurora Core will continue; open Runtime / "
                "Dependencies to review the required components."
            ],
            metrics={"enabled": True, "runtime_available": False},
            trace={"exception_type": type(error).__name__},
        )

    if runtime is None:
        return None, create_diagnostics(
            stage="voice.startup",
            success=False,
            reason="runtime_unavailable",
            warnings=["Voice is enabled but its runtime is unavailable."],
            metrics={"enabled": True, "runtime_available": False},
        )
    return runtime, create_diagnostics(
        stage="voice.startup",
        success=True,
        reason="ready",
        metrics={"enabled": True, "runtime_available": True},
    )


def create_voice_runtime(
    settings: Any,
    *,
    recorder: AudioRecorder | None,
    text_input_handler,
    stream_text_input_handler=None,
    state_callback: StateCallback | None = None,
    state_store: CompanionStateStore | None = None,
    stt_provider: SpeechToTextProvider | None = None,
    tts_provider: TextToSpeechProvider | None = None,
    playback: AudioPlaybackController | None = None,
    use_frame_pipeline: bool = False,
    input_device_name: str | None = None,
) -> RuntimeService | None:
    """Create the configured runtime, returning None when Voice is disabled.

    Providers are injectable so tests and future alternative backends do not
    need to change the application composition boundary.
    """

    if not _get_setting(settings, "voice.enabled", False):
        return None
    if recorder is None:
        raise ValueError("an AudioRecorder is required when Voice is enabled")
    if not callable(text_input_handler):
        raise TypeError("text_input_handler must be callable")
    if stream_text_input_handler is not None and not callable(stream_text_input_handler):
        raise TypeError("stream_text_input_handler must be callable or None")

    store = state_store or CompanionStateStore()
    stt = stt_provider or _create_stt(settings)
    tts = tts_provider or _create_tts(settings)
    audio_playback = playback or _create_playback(settings)
    wait_for_playback_completion = bool(
        _get_setting(settings, "voice.playback.wait_for_completion", True)
    )
    playback_timeout_seconds = float(
        _get_setting(settings, "voice.playback.timeout_seconds", 120.0)
    )
    tts_timeout_seconds = float(
        _get_setting(settings, "voice.tts.timeout_seconds", 30.0)
    )
    def build_orchestrator(
        current_recorder: AudioRecorder,
        *,
        cancel_event: Event | None = None,
    ) -> VoiceOrchestrator:
        return VoiceOrchestrator(
            recorder=current_recorder,
            stt_provider=stt,
            tts_provider=tts,
            playback=audio_playback,
            state_store=store,
            text_input_handler=text_input_handler,
            stream_text_input_handler=stream_text_input_handler,
            cancel_event=cancel_event or Event(),
            tts_timeout_seconds=tts_timeout_seconds,
            wait_for_playback_completion=wait_for_playback_completion,
            playback_timeout_seconds=playback_timeout_seconds,
        )

    orchestrator = build_orchestrator(recorder)
    session_manager = None
    if use_frame_pipeline:
        device_name = resolve_voice_input_device(settings, input_device_name)
        pre_roll_ms = int(_get_setting(settings, "voice.recorder.pre_roll_ms", 500))
        # Construct the shared buffer before the source so every producer has
        # one explicit distribution target.
        buffer = AudioFrameBuffer(
            max_duration_ms=max(
                pre_roll_ms,
                int(_get_setting(settings, "voice.recorder.pre_roll_buffer_ms", 1000)),
            )
        )
        source = FFmpegAudioFrameSource(
            device_name=device_name.strip(),
            buffer=buffer,
            sample_rate=int(_get_setting(settings, "voice.recorder.sample_rate", 16000)),
            channels=int(_get_setting(settings, "voice.recorder.channels", 1)),
            frame_duration_ms=int(_get_setting(settings, "voice.vad.frame_duration_ms", 20)),
            ffmpeg_path=resolve_ffmpeg_path(str(_get_setting(settings, "voice.recorder.ffmpeg_path", "ffmpeg"))),
        )
        vad = RMSVADAdapter(
            buffer.subscribe(pre_roll_ms=0),
            threshold=float(_get_setting(settings, "voice.vad.threshold", 0.014)),
            frame_duration_ms=int(_get_setting(settings, "voice.vad.frame_duration_ms", 20)),
            minimum_active_duration_ms=int(
                _get_setting(settings, "voice.vad.minimum_active_duration_ms", 100)
            ),
            start_threshold=_get_setting(settings, "voice.vad.start_threshold", None),
            stop_threshold=_get_setting(settings, "voice.vad.stop_threshold", None),
            peak_threshold=_get_setting(settings, "voice.vad.peak_threshold", 0.03),
        )
        session_manager = VoiceSessionManager(
            state_store=store,
            vad_adapter=vad,
            audio_buffer=buffer,
            audio_source=source,
            orchestrator_factory=build_orchestrator,
            pre_roll_ms=pre_roll_ms,
            inactivity_timeout_seconds=float(
                _get_setting(settings, "voice.session.inactivity_timeout_seconds", 180.0)
            ),
            maximum_recording_duration_seconds=float(
                _get_setting(settings, "voice.recorder.maximum_recording_duration", 180.0)
            ),
            silence_end_threshold_seconds=float(
                _get_setting(settings, "voice.recorder.silence_end_threshold", 0.8)
            ),
        )
    return RuntimeService(
        orchestrator,
        state_callback=state_callback,
        session_manager=session_manager,
        orchestrator_factory=(
            lambda: build_orchestrator(recorder)
            if session_manager is None
            else None
        ),
    )


def _create_stt(settings: Any) -> SpeechToTextProvider:
    provider_name = str(_get_setting(settings, "voice.stt.provider", "faster_whisper"))
    if provider_name == "faster_whisper":
        return FasterWhisperProvider(
            model_size=str(_get_setting(settings, "voice.stt.model_size", "small")),
            device=str(_get_setting(settings, "voice.stt.device", "auto")),
            compute_type=str(_get_setting(settings, "voice.stt.compute_type", "auto")),
        )
    if provider_name == "fake":
        return FakeSpeechToTextProvider()
    raise ValueError(f"unsupported Voice STT provider: {provider_name}")


def _create_tts(settings: Any) -> TextToSpeechProvider:
    provider_name = str(_get_setting(settings, "voice.tts.provider", "edge_tts"))
    if provider_name == "edge_tts":
        return EdgeTTSProvider(
            default_voice=str(
                _get_setting(settings, "voice.tts.voice", "zh-CN-XiaoxiaoNeural")
            )
        )
    if provider_name == "fake":
        return FakeTextToSpeechProvider()
    raise ValueError(f"unsupported Voice TTS provider: {provider_name}")


def _create_playback(settings: Any) -> AudioPlaybackController:
    backend = str(_get_setting(settings, "voice.playback.backend", "pygame"))
    if backend == "pygame":
        return RealPlaybackController()
    raise ValueError(f"unsupported Voice playback backend: {backend}")


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
