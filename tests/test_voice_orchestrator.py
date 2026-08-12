from threading import Event, Thread

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


def test_stream_handler_forwards_chunks_to_sentence_splitter_and_flushes():
    sentences = []

    def stream_handler(text, *, on_chunk, cancel_event):
        assert text == "hello"
        assert cancel_event.is_set() is False
        on_chunk("第一句。第二")
        on_chunk("句")
        return "第一句。第二句"

    orchestrator = build_orchestrator(
        playback=FakePlayback(auto_complete=True),
        stream_text_input_handler=stream_handler,
        sentence_callback=sentences.append,
    )

    result = orchestrator.run()

    assert result.success is True
    assert result.response_text == "第一句。第二句"
    assert sentences == ["第一句。", "第二句"]
    assert result.diagnostics["metrics"]["sentence_count"] == 2
    assert len(orchestrator.tts_provider.requests) == 2


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


def test_stream_tts_queue_cancellation_exits_worker():
    synthesis_started = Event()

    class BlockingTTS:
        def synthesize(self, text, options=None, *, timeout_seconds=None, cancel_event=None):
            synthesis_started.set()
            cancel_event.wait(1.0)
            return SpeechResult(audio_bytes=b"speech", diagnostics={"success": True})

    def stream_handler(_text, *, on_chunk, cancel_event):
        on_chunk("第一句。")
        return "第一句。"

    orchestrator = build_orchestrator(
        tts_provider=BlockingTTS(),
        stream_text_input_handler=stream_handler,
        playback_timeout_seconds=1.0,
    )
    results = []
    thread = Thread(target=lambda: results.append(orchestrator.run()), daemon=True)
    thread.start()

    assert synthesis_started.wait(1.0) is True
    orchestrator.cancel()
    thread.join(2.0)

    assert not thread.is_alive()
    assert results and results[0].cancelled is True


def test_interrupt_is_idempotent_and_invalidates_generation():
    orchestrator = build_orchestrator()
    generation_id = orchestrator.generation_id

    orchestrator.cancel()
    orchestrator.cancel()

    assert orchestrator.is_generation_active(generation_id) is False
    assert orchestrator.state_store.current_state is CompanionState.IDLE


def test_old_generation_does_not_enqueue_after_cancel():
    sentences = []
    orchestrator = build_orchestrator(sentence_callback=sentences.append)
    orchestrator.cancel()

    assert orchestrator.is_generation_active() is False
    assert sentences == []
