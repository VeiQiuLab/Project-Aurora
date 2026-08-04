import os
from pathlib import Path

import pytest

from modules.experience.audio import FakePlayback, FakeRecorder, RealPlaybackController
from modules.experience.state import CompanionState, CompanionStateStore
from modules.experience.voice.fake import FakeSpeechToTextProvider, FakeTextToSpeechProvider
from modules.experience.voice.integration import create_voice_runtime
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
    runtime = create_voice_runtime(
        voice_settings(),
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
