from modules.experience.audio import FakePlayback, FakeRecorder
from modules.experience.state import CompanionState, CompanionStateStore
from modules.experience.voice.fake import FakeSpeechToTextProvider, FakeTextToSpeechProvider
from modules.experience.voice.models import AudioInput, SpeechResult, TranscriptionResult
from modules.experience.voice.orchestrator import VoiceOrchestrator


def build_orchestrator(**overrides):
    values = {
        "recorder": FakeRecorder(AudioInput(kind="bytes", data=b"input")),
        "stt_provider": FakeSpeechToTextProvider(TranscriptionResult(text="hello")),
        "tts_provider": FakeTextToSpeechProvider(SpeechResult(audio_bytes=b"speech")),
        "playback": FakePlayback(),
        "state_store": CompanionStateStore(),
        "text_input_handler": lambda text: f"reply: {text}",
    }
    values.update(overrides)
    return VoiceOrchestrator(**values)


def test_fake_voice_pipeline_completes_and_returns_to_idle():
    orchestrator = build_orchestrator()
    events = []
    orchestrator.state_store.subscribe(events.append)

    result = orchestrator.run()

    assert result.success is True
    assert result.response_text == "reply: hello"
    assert orchestrator.state_store.current_state is CompanionState.IDLE
    assert [event.current_state for event in events] == [
        CompanionState.LISTENING,
        CompanionState.TRANSCRIBING,
        CompanionState.THINKING,
        CompanionState.SPEAKING,
        CompanionState.IDLE,
    ]


def test_stt_failure_falls_back_through_error_to_idle():
    orchestrator = build_orchestrator(
        stt_provider=FakeSpeechToTextProvider(error=RuntimeError("stt unavailable"))
    )
    events = []
    orchestrator.state_store.subscribe(events.append)

    result = orchestrator.run()

    assert result.success is False
    assert result.stage == "voice_pipeline"
    assert orchestrator.state_store.current_state is CompanionState.IDLE
    assert [event.current_state for event in events][-2:] == [
        CompanionState.ERROR,
        CompanionState.IDLE,
    ]


def test_tts_and_playback_failures_fall_back_to_idle():
    for overrides, expected_stage in (
        ({"tts_provider": FakeTextToSpeechProvider(error=RuntimeError("tts unavailable"))}, "tts"),
        ({"playback": FakePlayback(play_error=RuntimeError("speaker unavailable"))}, "playback"),
    ):
        orchestrator = build_orchestrator(**overrides)
        result = orchestrator.run()

        assert result.success is False
        assert result.stage == expected_stage
        assert orchestrator.state_store.current_state is CompanionState.IDLE


def test_cancel_stops_runtime_and_returns_to_idle():
    recorder = FakeRecorder(AudioInput(kind="bytes", data=b"input"))
    orchestrator = build_orchestrator(recorder=recorder)
    orchestrator.text_input_handler = lambda _text: (orchestrator.cancel() or "never used")

    result = orchestrator.run()

    assert result.success is False
    assert result.cancelled is True
    assert recorder.cancel_calls == 1
    assert orchestrator.state_store.current_state is CompanionState.IDLE


def test_force_idle_recovers_orchestrator_state():
    orchestrator = build_orchestrator()
    orchestrator.state_store.transition(CompanionState.THINKING)

    orchestrator.state_store.force_idle(reason="test_recovery")

    assert orchestrator.state_store.current_state is CompanionState.IDLE
