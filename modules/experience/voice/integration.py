"""Application composition for the optional full Voice Experience pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from modules.experience.audio.playback import AudioPlaybackController
from modules.experience.audio.recorder import AudioRecorder
from modules.experience.audio.real_playback import RealPlaybackController
from modules.experience.state import CompanionStateStore

from .fake import FakeSpeechToTextProvider, FakeTextToSpeechProvider
from .interfaces import SpeechToTextProvider, TextToSpeechProvider
from .orchestrator import VoiceOrchestrator
from .providers.edge_tts import EdgeTTSProvider
from .providers.faster_whisper import FasterWhisperProvider
from .runtime import RuntimeService, StateCallback


def create_voice_runtime(
    settings: Any,
    *,
    recorder: AudioRecorder | None,
    text_input_handler,
    state_callback: StateCallback | None = None,
    state_store: CompanionStateStore | None = None,
    stt_provider: SpeechToTextProvider | None = None,
    tts_provider: TextToSpeechProvider | None = None,
    playback: AudioPlaybackController | None = None,
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

    store = state_store or CompanionStateStore()
    stt = stt_provider or _create_stt(settings)
    tts = tts_provider or _create_tts(settings)
    audio_playback = playback or _create_playback(settings)
    orchestrator = VoiceOrchestrator(
        recorder=recorder,
        stt_provider=stt,
        tts_provider=tts,
        playback=audio_playback,
        state_store=store,
        text_input_handler=text_input_handler,
        wait_for_playback_completion=bool(
            _get_setting(settings, "voice.playback.wait_for_completion", True)
        ),
        playback_timeout_seconds=float(
            _get_setting(settings, "voice.playback.timeout_seconds", 120.0)
        ),
    )
    return RuntimeService(orchestrator, state_callback=state_callback)


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
