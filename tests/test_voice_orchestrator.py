from threading import Event, Thread

from modules.experience.audio import FakePlayback, FakeRecorder
from modules.experience.audio.playback import PlaybackEvent, PlaybackEventType
from modules.experience.state import CompanionState, CompanionStateStore
from modules.experience.voice.fake import FakeSpeechToTextProvider, FakeTextToSpeechProvider
from modules.experience.voice.models import (
    AudioInput,
    SpeechResult,
    SpeechSegment,
    TranscriptionResult,
)
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
    assert result.stage == "stt"
    assert "stt unavailable" in result.diagnostics["reason"]
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


def test_segment_indices_restart_for_each_generation_and_trace_ownership():
    def stream_handler(_text, *, on_chunk, cancel_event):
        on_chunk("第一句。第二句。第三句。")
        return "第一句。第二句。第三句。"

    orchestrator = build_orchestrator(
        playback=FakePlayback(auto_complete=True),
        stream_text_input_handler=stream_handler,
    )
    traces = []
    for generation_id in ("generation-1", "generation-2"):
        orchestrator.set_generation_context("session", generation_id)
        result = orchestrator.run()
        assert result.success is True
        traces.append(result.diagnostics["trace"]["speech_segments"])

    for generation_id, trace in zip(("generation-1", "generation-2"), traces):
        enqueued = [item for item in trace if item["event"] == "segment_enqueued"]
        assert [item["segment_index"] for item in enqueued] == [0, 1, 2]
        assert {item["session_id"] for item in enqueued} == {"session"}
        assert {item["generation_id"] for item in enqueued} == {generation_id}


def test_empty_chunks_do_not_consume_segment_index():
    def stream_handler(_text, *, on_chunk, cancel_event):
        on_chunk("   ")
        on_chunk("真正句子。")
        return "真正句子。"

    orchestrator = build_orchestrator(
        playback=FakePlayback(auto_complete=True),
        stream_text_input_handler=stream_handler,
    )
    result = orchestrator.run()

    assert result.success is True
    enqueued = [
        item
        for item in result.diagnostics["trace"]["speech_segments"]
        if item["event"] == "segment_enqueued"
    ]
    assert [item["segment_index"] for item in enqueued] == [0]


def test_cancel_immediately_clears_splitter_and_late_chunk_cannot_pollute_next_generation():
    handler_ready = Event()
    release_handler = Event()
    old_result = []

    def old_handler(_text, *, on_chunk, cancel_event):
        on_chunk("旧 generation 未完文本")
        handler_ready.set()
        release_handler.wait(2.0)
        on_chunk("迟到后缀。")
        return "旧 generation 未完文本迟到后缀。"

    orchestrator = build_orchestrator(
        playback=FakePlayback(auto_complete=True),
        stream_text_input_handler=old_handler,
    )
    orchestrator.set_generation_context("session", "old")
    thread = Thread(target=lambda: old_result.append(orchestrator.run()), daemon=True)
    thread.start()
    assert handler_ready.wait(1.0) is True
    assert orchestrator._active_splitter.pending_text

    orchestrator.cancel()
    assert orchestrator._active_splitter.pending_text == ""
    orchestrator.set_generation_context("session", "new")
    release_handler.set()
    thread.join(2.0)

    assert not thread.is_alive()
    assert old_result[0].cancelled is True
    assert orchestrator.tts_provider.requests == []

    def new_handler(_text, *, on_chunk, cancel_event):
        on_chunk("新 generation 句子。")
        return "新 generation 句子。"

    orchestrator.stream_text_input_handler = new_handler
    new_result = orchestrator.run()
    assert new_result.success is True
    assert [request[0] for request in orchestrator.tts_provider.requests] == [
        "新 generation 句子。"
    ]


def test_cancel_during_synthesize_drops_late_speech_before_playback():
    synthesis_started = Event()
    release_synthesis = Event()

    class LateTTS:
        def synthesize(self, text, options=None, *, timeout_seconds=None, cancel_event=None):
            synthesis_started.set()
            release_synthesis.wait(2.0)
            return SpeechResult(audio_bytes=b"late", diagnostics={"success": True})

    def stream_handler(_text, *, on_chunk, cancel_event):
        on_chunk("会被取消的句子。")
        return "会被取消的句子。"

    playback = FakePlayback(auto_complete=True)
    orchestrator = build_orchestrator(
        tts_provider=LateTTS(),
        playback=playback,
        stream_text_input_handler=stream_handler,
    )
    results = []
    thread = Thread(target=lambda: results.append(orchestrator.run()), daemon=True)
    thread.start()
    assert synthesis_started.wait(1.0) is True

    orchestrator.cancel()
    release_synthesis.set()
    thread.join(2.0)

    assert not thread.is_alive()
    assert results[0].cancelled is True
    assert playback.played == []
    trace = results[0].diagnostics["trace"]["speech_segments"]
    assert any(item["event"] == "segment_cancelled" for item in trace)
    assert not any(item["event"] == "segment_completed" for item in trace)


def test_generation_failure_is_fail_fast_and_later_segments_are_not_spoken():
    class FirstFailsTTS:
        def __init__(self):
            self.requests = []

        def synthesize(self, text, options=None, *, timeout_seconds=None, cancel_event=None):
            self.requests.append(text)
            raise RuntimeError("tts generation failed")

    provider = FirstFailsTTS()
    playback = FakePlayback(auto_complete=True)

    def stream_handler(_text, *, on_chunk, cancel_event):
        on_chunk("失败句。不应播放的后续句。")
        return "失败句。不应播放的后续句。"

    orchestrator = build_orchestrator(
        tts_provider=provider,
        playback=playback,
        stream_text_input_handler=stream_handler,
    )
    result = orchestrator.run()

    assert result.success is False
    assert result.cancelled is False
    assert result.stage == "tts"
    assert provider.requests == ["失败句。"]
    assert playback.played == []
    trace = result.diagnostics["trace"]["speech_segments"]
    assert any(item["event"] == "segment_failed" for item in trace)
    assert any(
        item["event"] == "stale_dropped" and item["segment_index"] == 1
        for item in trace
    )


def test_late_playback_completion_and_error_cannot_mutate_new_generation():
    playback = FakePlayback(auto_complete=True)
    orchestrator = build_orchestrator(playback=playback)
    orchestrator.set_generation_context("session", "old")
    result = orchestrator.run()
    assert result.success is True
    old_speech = playback.played[-1]

    orchestrator.set_generation_context("session", "new")
    orchestrator._playback_error = "new-generation-value"
    orchestrator._playback_finished.clear()
    orchestrator._handle_playback_event(
        PlaybackEvent(
            event_type=PlaybackEventType.COMPLETED,
            speech=old_speech,
        )
    )
    orchestrator._handle_playback_event(
        PlaybackEvent(
            event_type=PlaybackEventType.FAILED,
            speech=old_speech,
            error="late old error",
        )
    )

    assert orchestrator._playback_error == "new-generation-value"
    assert orchestrator._playback_finished.is_set() is False
    assert orchestrator.is_generation_active("new", session_id="session") is True


def test_cancelled_n_and_late_tts_completion_are_isolated_from_running_n_plus_one():
    old_started = Event()
    release_old = Event()

    class TwoGenerationTTS:
        def __init__(self):
            self.requests = []

        def synthesize(self, text, options=None, *, timeout_seconds=None, cancel_event=None):
            self.requests.append(text)
            if text == "old sentence.":
                old_started.set()
                release_old.wait(2.0)
            return SpeechResult(
                audio_bytes=text.encode("utf-8"),
                diagnostics={"success": True},
            )

    provider = TwoGenerationTTS()
    playback = FakePlayback(auto_complete=True)
    orchestrator = build_orchestrator(
        tts_provider=provider,
        playback=playback,
        stream_text_input_handler=lambda _text, *, on_chunk, cancel_event: (
            on_chunk("old sentence.") or "old sentence."
        ),
    )
    orchestrator.set_generation_context("session", "old")
    old_results = []
    old_thread = Thread(target=lambda: old_results.append(orchestrator.run()), daemon=True)
    old_thread.start()
    assert old_started.wait(1.0) is True

    orchestrator.cancel()
    orchestrator.set_generation_context("session", "new")
    orchestrator.stream_text_input_handler = (
        lambda _text, *, on_chunk, cancel_event: (
            on_chunk("new sentence.") or "new sentence."
        )
    )
    new_result = orchestrator.run()
    release_old.set()
    old_thread.join(2.0)

    assert new_result.success is True
    assert old_results[0].cancelled is True
    assert provider.requests == ["old sentence.", "new sentence."]
    assert [speech.audio_bytes for speech in playback.played] == [b"new sentence."]
    assert orchestrator._active_splitter is None
    assert orchestrator._tts_queue is None
    assert orchestrator._legacy_playback_context is None
    assert orchestrator._playback_owners == {}


def test_cancelled_generation_waiter_does_not_stop_new_generation_playback():
    playback = FakePlayback(auto_complete=False)
    orchestrator = build_orchestrator(playback=playback)
    old_segment = SpeechSegment("session", "old", 0, "old sentence.")
    old_speech = SpeechResult(audio_bytes=b"old")
    new_segment = SpeechSegment("session", "new", 0, "new sentence.")
    new_speech = SpeechResult(audio_bytes=b"new")
    old_cancel_event = Event()
    old_cancel_event.set()

    orchestrator.set_generation_context("session", "new")
    with orchestrator._lock:
        orchestrator._legacy_playback_context = (new_segment, new_speech)
        orchestrator._playback_owners[id(new_speech)] = new_segment
    playback.play(new_speech)
    orchestrator._playback_finished.clear()

    orchestrator._wait_for_playback(old_segment, old_speech, old_cancel_event)

    assert playback.stop_calls == 0
    assert playback.is_playing() is True
    assert orchestrator._legacy_playback_context == (new_segment, new_speech)
