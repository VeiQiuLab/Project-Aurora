"""Application composition for the optional full Voice Experience pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from modules.experience.audio.playback import AudioPlaybackController
from modules.experience.audio.recorder import AudioRecorder
from modules.experience.audio.real_playback import RealPlaybackController
from modules.experience.audio.ffmpeg_source import FFmpegAudioFrameSource
from modules.experience.audio.frame_pipeline import AudioFrameBuffer
from modules.experience.audio.device_discovery import resolve_ffmpeg_path, resolve_voice_input_device
from modules.experience.audio.vad import RMSVADAdapter
from modules.experience.state import CompanionStateStore

from .fake import FakeSpeechToTextProvider, FakeTextToSpeechProvider
from .interfaces import SpeechToTextProvider, TextToSpeechProvider
from .orchestrator import VoiceOrchestrator
from .session import VoiceSessionManager
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

    def build_orchestrator(current_recorder: AudioRecorder) -> VoiceOrchestrator:
        return VoiceOrchestrator(
            recorder=current_recorder,
            stt_provider=stt,
            tts_provider=tts,
            playback=audio_playback,
            state_store=store,
            text_input_handler=text_input_handler,
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
                _get_setting(settings, "voice.recorder.silence_end_threshold", 10.0)
            ),
        )
    return RuntimeService(
        orchestrator,
        state_callback=state_callback,
        session_manager=session_manager,
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
