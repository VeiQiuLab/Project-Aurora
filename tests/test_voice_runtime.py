from threading import Event

from modules.experience.audio import FakePlayback, FakeRecorder
from modules.experience.state import CompanionState, CompanionStateStore
from modules.experience.voice.fake import FakeSpeechToTextProvider, FakeTextToSpeechProvider
from modules.experience.voice.models import AudioInput, SpeechResult, TranscriptionResult
from modules.experience.voice.orchestrator import VoiceOrchestrator
from modules.experience.voice.runtime import RuntimeService
from modules.experience.voice.session import VoiceSessionManager


def build_runtime(**overrides):
    state_callback = overrides.pop("state_callback", None)
    session_manager = overrides.pop("session_manager", None)
    values = {
        "recorder": FakeRecorder(AudioInput(kind="bytes", data=b"input")),
        "stt_provider": FakeSpeechToTextProvider(TranscriptionResult(text="hello")),
        "tts_provider": FakeTextToSpeechProvider(SpeechResult(audio_bytes=b"speech")),
        "playback": FakePlayback(),
        "state_store": CompanionStateStore(),
        "text_input_handler": lambda text: f"reply: {text}",
    }
    values.update(overrides)
    return RuntimeService(
        VoiceOrchestrator(**values),
        state_callback=state_callback,
        session_manager=session_manager,
    )


def test_runtime_runs_fake_pipeline_in_background_and_forwards_state():
    states = []
    runtime = build_runtime(state_callback=lambda event: states.append(event.current_state))

    assert runtime.start_voice_session() is True
    result = runtime.wait_for_session(timeout_seconds=2)

    assert result is not None and result.success is True
    assert runtime.session_running is False
    assert states == [
        CompanionState.LISTENING,
        CompanionState.TRANSCRIBING,
        CompanionState.THINKING,
        CompanionState.SPEAKING,
        CompanionState.IDLE,
    ]


def test_runtime_rejects_overlapping_session_and_preserves_failure_result():
    started = Event()
    release = Event()

    def blocking_text_handler(_text):
        started.set()
        release.wait(2)
        return "reply"

    runtime = build_runtime(text_input_handler=blocking_text_handler)
    assert runtime.start_voice_session() is True
    assert started.wait(1) is True
    assert runtime.start_voice_session() is False

    release.set()
    result = runtime.wait_for_session(timeout_seconds=2)

    assert result is not None and result.success is True


def test_runtime_cancel_stops_active_session_and_returns_cancelled_result():
    started = Event()
    release = Event()

    def blocking_text_handler(_text):
        started.set()
        release.wait(2)
        return "unused"

    runtime = build_runtime(text_input_handler=blocking_text_handler)
    assert runtime.start_voice_session() is True
    assert started.wait(1) is True
    assert runtime.cancel_voice_session() is True
    release.set()

    result = runtime.wait_for_session(timeout_seconds=2)

    assert result is not None and result.cancelled is True
    assert runtime.session_running is False
    assert runtime.orchestrator.state_store.current_state is CompanionState.IDLE


def test_runtime_cancel_when_idle_returns_false():
    runtime = build_runtime()

    assert runtime.cancel_voice_session() is False


def test_runtime_delegates_to_frame_session_manager_and_preserves_shared_state():
    state_store = CompanionStateStore()
    manager = VoiceSessionManager(
        state_store=state_store,
        wait_for_voice=lambda _cancel, _timeout: False,
        run_cycle=lambda: None,
        inactivity_timeout_seconds=0.02,
        wait_slice_seconds=0.005,
    )
    runtime = build_runtime(state_store=state_store, session_manager=manager)

    assert runtime.start_voice_session() is True
    result = runtime.wait_for_session(timeout_seconds=2)

    assert result is not None
    assert result.success is True
    assert result.stage == "inactivity_timeout"
    assert runtime.orchestrator.state_store is manager.state_store
    assert state_store.current_state is CompanionState.IDLE
