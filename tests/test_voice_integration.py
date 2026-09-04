import os
from pathlib import Path

import pytest

from modules.experience.audio import FakePlayback, FakeRecorder, RealPlaybackController
from modules.experience.state import CompanionState, CompanionStateStore
from modules.experience.voice.fake import FakeSpeechToTextProvider, FakeTextToSpeechProvider
from modules.experience.audio.device_discovery import AudioDeviceDiscoveryError
from modules.experience.voice.integration import create_optional_voice_runtime, create_voice_runtime
from modules.experience.voice.models import AudioInput, SpeechResult, TranscriptionResult
from modules.experience.voice.providers.edge_tts import EdgeTTSProvider
from modules.experience.voice.providers.faster_whisper import FasterWhisperProvider


RUN_REAL_VOICE_E2E = os.environ.get("AURORA_RUN_REAL_VOICE_E2E") == "1"
TEST_AUDIO_PATH = Path(
    os.environ.get("AURORA_TEST_AUDIO_PATH", r"C:\Users\X\Desktop\test.wav")
)


def voice_settings(enabled=True):
    return {
        "voice": {
            "enabled": enabled,
            "recorder": {"device_name": "test-device"},
            "stt": {"provider": "fake"},
            "tts": {"provider": "fake"},
            "playback": {"backend": "pygame", "wait_for_completion": True},
        }
    }


def ready_dependencies(_settings):
    return {"ready": True, "missing": []}


def test_optional_voice_runtime_skips_factory_when_voice_is_disabled():
    calls = []

    runtime, diagnostics = create_optional_voice_runtime(
        voice_settings(False),
        lambda: calls.append("runtime"),
        dependency_checker=lambda _settings: calls.append("dependencies"),
    )

    assert runtime is None
    assert calls == []
    assert diagnostics["success"] is True
    assert diagnostics["reason"] == "disabled"


def test_optional_voice_runtime_degrades_when_ffmpeg_is_missing():
    calls = []

    runtime, diagnostics = create_optional_voice_runtime(
        voice_settings(),
        lambda: calls.append("runtime"),
        dependency_checker=lambda _settings: {
            "ready": False,
            "missing": [{"key": "ffmpeg", "name": "ffmpeg"}],
        },
    )

    assert runtime is None
    assert calls == []
    assert diagnostics["success"] is False
    assert diagnostics["reason"] == "dependency_missing"
    assert diagnostics["metrics"]["missing_dependencies"] == ["ffmpeg"]
    assert "ffmpeg" in diagnostics["warnings"][0]


def test_optional_voice_runtime_uses_unified_dependency_manager_by_default(monkeypatch):
    calls = []

    class Manager:
        def __init__(self, settings):
            calls.append(settings)

        def check_voice_requirements(self):
            return {
                "ready": False,
                "missing": [{"key": "whisper_model", "name": "Whisper Model"}],
            }

    monkeypatch.setattr(
        "modules.experience.voice.integration.RuntimeDependencyManager", Manager
    )
    runtime, diagnostics = create_optional_voice_runtime(
        voice_settings(),
        lambda: (_ for _ in ()).throw(AssertionError("runtime must not start")),
    )

    assert runtime is None
    assert len(calls) == 1
    assert diagnostics["metrics"]["missing_dependencies"] == ["Whisper Model"]


def test_optional_voice_runtime_contains_dependency_check_failure():
    def fail_check(_settings):
        raise RuntimeError("dependency probe failed")

    runtime, diagnostics = create_optional_voice_runtime(
        voice_settings(),
        lambda: object(),
        dependency_checker=fail_check,
    )

    assert runtime is None
    assert diagnostics["success"] is False
    assert diagnostics["reason"] == "dependency_check_failed"
    assert diagnostics["trace"]["exception_type"] == "RuntimeError"
    assert "dependency probe failed" not in diagnostics["warnings"][0]
    assert "Runtime / Dependencies" in diagnostics["warnings"][0]


def test_optional_voice_runtime_degrades_when_device_discovery_fails():
    def fail_discovery():
        raise AudioDeviceDiscoveryError("FFmpeg dshow enumeration failed")

    runtime, diagnostics = create_optional_voice_runtime(
        voice_settings(),
        fail_discovery,
        dependency_checker=ready_dependencies,
    )

    assert runtime is None
    assert diagnostics["success"] is False
    assert diagnostics["reason"] == "audio_device_unavailable"
    assert diagnostics["trace"]["exception_type"] == "AudioDeviceDiscoveryError"
    assert "FFmpeg dshow enumeration failed" not in diagnostics["warnings"][0]
    assert "usable microphone" in diagnostics["warnings"][0]


def test_optional_voice_runtime_contains_unexpected_voice_initialization_failure():
    def fail_initialization():
        raise RuntimeError("provider initialization failed")

    runtime, diagnostics = create_optional_voice_runtime(
        voice_settings(),
        fail_initialization,
        dependency_checker=ready_dependencies,
    )

    assert runtime is None
    assert diagnostics["success"] is False
    assert diagnostics["reason"] == "initialization_failed"
    assert diagnostics["trace"]["exception_type"] == "RuntimeError"
    assert "provider initialization failed" not in diagnostics["warnings"][0]


def test_optional_voice_runtime_returns_ready_runtime_and_diagnostics():
    expected = object()

    runtime, diagnostics = create_optional_voice_runtime(
        voice_settings(),
        lambda: expected,
        dependency_checker=ready_dependencies,
    )

    assert runtime is expected
    assert diagnostics["success"] is True
    assert diagnostics["reason"] == "ready"
    assert diagnostics["metrics"]["runtime_available"] is True


def test_voice_disabled_by_default_returns_no_runtime():
    runtime = create_voice_runtime(
        voice_settings(False),
        recorder=None,
        text_input_handler=lambda _text: "reply",
    )

    assert runtime is None


def test_enabled_runtime_composes_fake_voice_pipeline():
    recorder = FakeRecorder(AudioInput(kind="bytes", data=b"input"))
    state_store = CompanionStateStore()
    received = []
    runtime = create_voice_runtime(
        voice_settings(),
        recorder=recorder,
        text_input_handler=lambda text: received.append(text) or "reply",
        state_store=state_store,
        stt_provider=FakeSpeechToTextProvider(TranscriptionResult(text="hello")),
        tts_provider=FakeTextToSpeechProvider(SpeechResult(audio_bytes=b"speech")),
        playback=FakePlayback(auto_complete=True),
    )

    assert runtime is not None
    assert runtime.start_voice_session() is True
    result = runtime.wait_for_session(timeout_seconds=2)

    assert result is not None and result.success is True
    assert received == ["hello"]
    assert state_store.current_state is CompanionState.IDLE


def test_enabled_runtime_uses_real_provider_defaults_without_loading_them():
    configured = voice_settings()
    configured["voice"].pop("stt")
    configured["voice"].pop("tts")
    runtime = create_voice_runtime(
        configured,
        recorder=FakeRecorder(),
        text_input_handler=lambda _text: "reply",
    )

    assert runtime is not None
    assert runtime.orchestrator.stt_provider.__class__.__name__ == "FasterWhisperProvider"
    assert runtime.orchestrator.tts_provider.__class__.__name__ == "EdgeTTSProvider"
    assert runtime.orchestrator.playback.__class__.__name__ == "RealPlaybackController"


def test_frame_pipeline_runtime_uses_session_manager_with_shared_state():
    state_store = CompanionStateStore()
    runtime = create_voice_runtime(
        voice_settings(),
        recorder=FakeRecorder(AudioInput(kind="bytes", data=b"input")),
        text_input_handler=lambda _text: "reply",
        state_store=state_store,
        stt_provider=FakeSpeechToTextProvider(TranscriptionResult(text="hello")),
        tts_provider=FakeTextToSpeechProvider(SpeechResult(audio_bytes=b"speech")),
        playback=FakePlayback(auto_complete=True),
        use_frame_pipeline=True,
    )

    assert runtime is not None
    assert runtime.session_manager is not None
    assert runtime.session_manager.state_store is state_store
    assert runtime.orchestrator.state_store is state_store


@pytest.mark.skipif(not RUN_REAL_VOICE_E2E, reason="set AURORA_RUN_REAL_VOICE_E2E=1")
def test_e2e_fake_stt_real_tts():
    runtime = create_voice_runtime(
        voice_settings(),
        recorder=FakeRecorder(AudioInput(kind="bytes", data=b"input")),
        text_input_handler=lambda _text: "你好 Aurora",
        stt_provider=FakeSpeechToTextProvider(TranscriptionResult(text="hello")),
        tts_provider=EdgeTTSProvider(),
        playback=FakePlayback(auto_complete=True),
    )

    result = runtime.orchestrator.run()

    assert result.success is True
    assert result.speech is not None and result.speech.audio_path


@pytest.mark.skipif(
    not RUN_REAL_VOICE_E2E or not TEST_AUDIO_PATH.is_file(),
    reason="set AURORA_RUN_REAL_VOICE_E2E=1 and provide AURORA_TEST_AUDIO_PATH",
)
def test_e2e_real_stt_fake_tts():
    runtime = create_voice_runtime(
        voice_settings(),
        recorder=FakeRecorder(AudioInput(kind="file", path=str(TEST_AUDIO_PATH))),
        text_input_handler=lambda text: f"reply: {text}",
        stt_provider=FasterWhisperProvider(model_size="tiny", device="cpu", compute_type="int8"),
        tts_provider=FakeTextToSpeechProvider(SpeechResult(audio_bytes=b"fake")),
        playback=FakePlayback(auto_complete=True),
    )

    result = runtime.orchestrator.run()

    assert result.success is True
    assert result.transcription is not None and result.transcription.text


@pytest.mark.skipif(
    not RUN_REAL_VOICE_E2E or not TEST_AUDIO_PATH.is_file(),
    reason="set AURORA_RUN_REAL_VOICE_E2E=1 and provide AURORA_TEST_AUDIO_PATH",
)
def test_e2e_real_stt_real_tts_real_playback():
    runtime = create_voice_runtime(
        voice_settings(),
        recorder=FakeRecorder(AudioInput(kind="file", path=str(TEST_AUDIO_PATH))),
        text_input_handler=lambda text: f"reply: {text}",
        stt_provider=FasterWhisperProvider(model_size="tiny", device="cpu", compute_type="int8"),
        tts_provider=EdgeTTSProvider(),
        playback=RealPlaybackController(),
    )

    try:
        result = runtime.orchestrator.run()
        assert result.success is True
    finally:
        try:
            import pygame

            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
                pygame.mixer.quit()
        except Exception:
            pass
