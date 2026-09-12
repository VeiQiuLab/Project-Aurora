from __future__ import annotations

from collections import deque
from threading import Event, Thread
from time import monotonic

import pytest

from modules.experience.audio import FakePlayback, FakeRecorder, StreamingPlaybackReport
from modules.experience.state import CompanionStateStore
from modules.experience.voice.fake import FakeSpeechToTextProvider
from modules.experience.voice.interfaces import StreamingTTSProvider, TTSProvider
from modules.experience.voice.models import (
    AudioInput,
    SpeechResult,
    SpeechSegment,
    StreamingSpeechResult,
    TranscriptionResult,
)
from modules.experience.voice.orchestrator import VoiceOrchestrator
from modules.experience.voice.providers.edge_tts import EdgeTTSProvider
from modules.experience.voice.runtime import RuntimeService
from modules.experience.voice.tts_router import TTSRouter


def _report(
    status: str,
    *,
    request_start: float,
    metadata_at: float,
    first_audio: float | None,
    playback_end: float,
    error: str = "",
) -> StreamingPlaybackReport:
    first_pcm = first_audio
    upstream_end = playback_end - 0.001 if status == "completed" else None
    received = 4800 if status == "completed" else 0
    return StreamingPlaybackReport(
        status=status,
        diagnostics={
            "success": status == "completed",
            "reason": status,
            "warnings": [],
            "metrics": {
                "request_start_monotonic": request_start,
                "provider_metadata_monotonic": metadata_at,
                "first_pcm_received_monotonic": first_pcm,
                "first_audio_submission_monotonic": first_audio,
                "upstream_end_monotonic": upstream_end,
                "playback_start_monotonic": first_audio,
                "playback_end_monotonic": playback_end,
                "request_to_first_audio_submission_ms": (
                    None
                    if first_audio is None
                    else round((first_audio - request_start) * 1000.0, 3)
                ),
                "audio_duration_ms": 100.0 if status == "completed" else 0.0,
                "sample_rate": 24000,
                "channels": 1,
                "received_pcm_bytes": received,
                "played_pcm_bytes": received,
                "underrun_count": 0,
                "buffer_peak_bytes": 4800,
                "cancel_latency_ms": 0.0 if status == "cancelled" else None,
                "producer_error": error,
                "playback_error": error if status == "failed" else "",
                "provider_close_error": "",
                "provider_closed": True,
                "audio_stream_stopped": True,
            },
        },
    )


class ControlledStreamingSession:
    def __init__(
        self,
        *,
        release: Event | None = None,
        terminal_status: str = "completed",
        raise_after_cancel: bool = False,
    ) -> None:
        self.release = release
        self.terminal_status = terminal_status
        self.raise_after_cancel = raise_after_cancel
        self.wait_started = Event()
        self.first_audio = Event()
        self.completed = Event()
        self.cancelled = Event()
        self.cancel_calls = 0
        self.speech: StreamingSpeechResult | None = None
        self.timings: dict[str, float] = {}
        self.first_audio_at: float | None = None

    def bind(self, speech: StreamingSpeechResult, timings: dict[str, float]) -> None:
        self.speech = speech
        self.timings = timings

    def wait(self, _timeout: float | None = None) -> StreamingPlaybackReport:
        self.wait_started.set()
        self.first_audio_at = monotonic()
        self.first_audio.set()
        if self.release is not None:
            while not self.release.wait(0.01):
                if self.cancelled.is_set():
                    break
        if self.cancelled.is_set() and self.raise_after_cancel:
            assert self.speech is not None
            self.speech.close()
            self.completed.set()
            raise OSError("incomplete PCM stream after response close")
        status = "cancelled" if self.cancelled.is_set() else self.terminal_status
        ended = monotonic()
        assert self.speech is not None
        self.speech.close()
        self.completed.set()
        return _report(
            status,
            request_start=self.timings["request_start_monotonic"],
            metadata_at=self.timings["provider_metadata_monotonic"],
            first_audio=self.first_audio_at,
            playback_end=ended,
            error="synthetic playback failure" if status == "failed" else "",
        )

    def cancel(self) -> None:
        self.cancel_calls += 1
        self.cancelled.set()
        if self.release is not None:
            self.release.set()
        if self.speech is not None:
            self.speech.cancel()


class ControlledStreamingController:
    def __init__(self, sessions: list[ControlledStreamingSession] | None = None) -> None:
        self.sessions = deque(sessions or [])
        self.play_calls: list[StreamingSpeechResult] = []

    def play(self, speech: StreamingSpeechResult, **timings: float):
        session = self.sessions.popleft() if self.sessions else ControlledStreamingSession()
        session.bind(speech, dict(timings))
        self.play_calls.append(speech)
        return session


class ControlledStreamingProvider(TTSProvider, StreamingTTSProvider):
    def __init__(self, *, fail_stream_index: int | None = None) -> None:
        self.fail_stream_index = fail_stream_index
        self.stream_calls: list[str] = []
        self.legacy_calls: list[str] = []
        self.closed: list[Event] = []
        self.call_events: list[Event] = []

    def synthesize(self, text, options=None, *, timeout_seconds=None, cancel_event=None):
        self.legacy_calls.append(text)
        return SpeechResult(audio_bytes=b"legacy", diagnostics={"success": True})

    def synthesize_stream(
        self, text, options=None, *, timeout_seconds=None, cancel_event=None
    ) -> StreamingSpeechResult:
        index = len(self.stream_calls)
        self.stream_calls.append(text)
        called = Event()
        called.set()
        self.call_events.append(called)
        if self.fail_stream_index == index:
            raise OSError("synthetic provider failure")
        closed = Event()
        self.closed.append(closed)
        return StreamingSpeechResult(
            metadata={
                "sample_format": "s16le",
                "bits_per_sample": 16,
                "sample_rate": 24000,
                "channels": 1,
                "interleaved": True,
            },
            chunks=iter((b"\0\0",)),
            diagnostics={"success": True, "reason": "stream_open"},
            _close=closed.set,
        )


class LegacyProvider(TTSProvider):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def synthesize(self, text, options=None, *, timeout_seconds=None, cancel_event=None):
        self.calls.append(text)
        return SpeechResult(audio_bytes=b"legacy", diagnostics={"success": True})


class TrackingEdgeProvider(EdgeTTSProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def synthesize(self, text, *_args, **_kwargs):
        self.calls.append(text)
        return SpeechResult(audio_bytes=b"edge", diagnostics={"success": True})


def _orchestrator(
    provider,
    controller,
    stream_handler,
    *,
    streaming_enabled: bool = True,
) -> VoiceOrchestrator:
    return VoiceOrchestrator(
        recorder=FakeRecorder(AudioInput(kind="bytes", data=b"input")),
        stt_provider=FakeSpeechToTextProvider(TranscriptionResult(text="test prompt")),
        tts_provider=provider,
        playback=FakePlayback(auto_complete=True),
        state_store=CompanionStateStore(),
        text_input_handler=lambda _text: "unused",
        stream_text_input_handler=stream_handler,
        wait_for_playback_completion=True,
        playback_timeout_seconds=2.0,
        streaming_enabled=streaming_enabled,
        streaming_playback=controller,
    )


def _one_sentence_handler(_text, *, on_chunk, cancel_event):
    assert not cancel_event.is_set()
    response = "这是一个用于队列测试的完整句子。"
    on_chunk(response)
    return response


def test_queue_selects_routed_streaming_capability_and_populates_segment_diagnostics():
    provider = ControlledStreamingProvider()
    controller = ControlledStreamingController()
    router = TTSRouter({"remote": provider}, default_provider="remote")
    orchestrator = _orchestrator(router, controller, _one_sentence_handler)

    result = orchestrator.run()

    assert result.success is True
    assert provider.stream_calls == ["这是一个用于队列测试的完整句子。"]
    assert provider.legacy_calls == []
    assert len(controller.play_calls) == 1
    assert all(closed.is_set() for closed in provider.closed)
    metrics = result.diagnostics["metrics"]
    assert metrics["streaming_selected"] is True
    assert metrics["streaming_status"] == "completed"
    segments = result.diagnostics["trace"]["streaming_segments"]
    assert len(segments) == 1
    expected = {
        "session_id",
        "generation_id",
        "segment_index",
        "provider",
        "streaming_selected",
        "segment_emit_monotonic",
        "tts_request_start",
        "first_pcm_received",
        "first_audio_submission",
        "upstream_end",
        "playback_end",
        "audio_duration_ms",
        "received_pcm_bytes",
        "played_pcm_bytes",
        "underrun_count",
        "buffer_peak_bytes",
        "cancel_latency_ms",
        "status",
        "error",
    }
    assert expected <= segments[0].keys()
    assert "text" not in segments[0]
    assert segments[0]["received_pcm_bytes"] == 4800
    assert segments[0]["played_pcm_bytes"] == 4800


@pytest.mark.parametrize("provider_kind", ["disabled", "legacy", "edge"])
def test_queue_preserves_legacy_path_when_streaming_is_unavailable(provider_kind):
    if provider_kind == "disabled":
        provider = ControlledStreamingProvider()
        streaming_enabled = False
    elif provider_kind == "edge":
        provider = TrackingEdgeProvider()
        streaming_enabled = True
    else:
        provider = LegacyProvider()
        streaming_enabled = True
    controller = ControlledStreamingController()
    orchestrator = _orchestrator(
        provider,
        controller,
        _one_sentence_handler,
        streaming_enabled=streaming_enabled,
    )

    result = orchestrator.run()

    assert result.success is True
    assert controller.play_calls == []
    assert len(orchestrator.playback.played) == 1
    if isinstance(provider, ControlledStreamingProvider):
        assert provider.stream_calls == []
        assert len(provider.legacy_calls) == 1
    else:
        assert len(provider.calls) == 1


def test_llm_continues_while_segment_zero_plays_and_segments_execute_strictly_fifo():
    release_zero = Event()
    zero = ControlledStreamingSession(release=release_zero)
    one = ControlledStreamingSession()
    two = ControlledStreamingSession()
    provider = ControlledStreamingProvider()
    controller = ControlledStreamingController([zero, one, two])
    llm_complete = Event()

    def handler(_text, *, on_chunk, cancel_event):
        on_chunk("第一段已经可以开始说话。")
        assert zero.first_audio.wait(1.0)
        assert not llm_complete.is_set()
        on_chunk("第二段在第一段播放时进入队列。第三段保持严格顺序。")
        assert provider.stream_calls == ["第一段已经可以开始说话。"]
        release_zero.set()
        # Windows' monotonic clock may return the same tick to both threads.
        # Keep the fake LLM open for one tick so the ordering assertion is exact.
        Event().wait(0.02)
        llm_complete.set()
        return "第一段已经可以开始说话。第二段在第一段播放时进入队列。第三段保持严格顺序。"

    result = _orchestrator(provider, controller, handler).run()

    assert result.success is True
    assert provider.stream_calls == [
        "第一段已经可以开始说话。",
        "第二段在第一段播放时进入队列。",
        "第三段保持严格顺序。",
    ]
    assert zero.completed.is_set() and one.completed.is_set() and two.completed.is_set()
    timing = result.diagnostics["trace"]["turn_timing"]
    assert timing["first_audio_submission_monotonic"] < timing["llm_complete_monotonic"]
    assert result.diagnostics["metrics"]["first_audio_before_llm_complete"] is True
    assert result.diagnostics["metrics"]["first_audio_lead_before_llm_complete_ms"] > 0


def test_turn_does_not_complete_until_final_segment_playback_finishes():
    release_final = Event()
    final_session = ControlledStreamingSession(release=release_final)
    orchestrator = _orchestrator(
        ControlledStreamingProvider(),
        ControlledStreamingController(
            [ControlledStreamingSession(), final_session]
        ),
        lambda _text, *, on_chunk, cancel_event: (
            on_chunk("第一段正常完成。第二段必须等待播放结束。")
            or "第一段正常完成。第二段必须等待播放结束。"
        ),
    )
    outcome: list[object] = []
    thread = Thread(target=lambda: outcome.append(orchestrator.run()), daemon=True)
    thread.start()

    assert final_session.wait_started.wait(1.0)
    assert thread.is_alive()
    release_final.set()
    thread.join(2.0)

    assert not thread.is_alive()
    assert outcome and outcome[0].success is True
    timing = outcome[0].diagnostics["trace"]["turn_timing"]
    assert timing["final_playback_end_monotonic"] >= timing["llm_complete_monotonic"]


def test_cancel_active_stream_discards_pending_and_n_plus_one_recovers():
    release = Event()
    cancelled_session = ControlledStreamingSession(release=release)
    provider = ControlledStreamingProvider()
    controller = ControlledStreamingController([cancelled_session])
    orchestrator = _orchestrator(
        provider,
        controller,
        lambda _text, *, on_chunk, cancel_event: (
            on_chunk("第一段正在播放。第二段不应播放。第三段也不应播放。")
            or "第一段正在播放。第二段不应播放。第三段也不应播放。"
        ),
    )
    runtime = RuntimeService(orchestrator)
    assert runtime.start_voice_session() is True
    assert cancelled_session.first_audio.wait(1.0)

    assert runtime.cancel_voice_session() is True
    orchestrator.cancel()
    first = runtime.wait_for_session(2.0)

    assert first is not None and first.cancelled is True
    assert provider.stream_calls == ["第一段正在播放。"]
    assert cancelled_session.cancel_calls >= 1
    assert provider.closed[0].is_set()
    assert orchestrator._current_streaming_session is None
    assert orchestrator._streaming_playback_context is None

    recovery_session = ControlledStreamingSession()
    controller.sessions.append(recovery_session)
    orchestrator.stream_text_input_handler = _one_sentence_handler
    assert runtime.start_voice_session() is True
    second = runtime.wait_for_session(2.0)

    assert second is not None and second.success is True
    assert provider.stream_calls[-1] == "这是一个用于队列测试的完整句子。"
    assert runtime.close() is True


def test_cancel_side_effect_error_remains_cancelled_and_clears_active_owner():
    session = ControlledStreamingSession(release=Event(), raise_after_cancel=True)
    provider = ControlledStreamingProvider()
    orchestrator = _orchestrator(
        provider,
        ControlledStreamingController([session]),
        _one_sentence_handler,
    )
    runtime = RuntimeService(orchestrator)
    assert runtime.start_voice_session() is True
    assert session.first_audio.wait(1.0)

    assert runtime.cancel_voice_session() is True
    result = runtime.wait_for_session(2.0)

    assert result is not None and result.cancelled is True
    assert result.stage == "cancelled"
    assert orchestrator._streaming_playback_context is None
    assert orchestrator._current_streaming_session is None
    assert runtime.close() is True


@pytest.mark.parametrize(
    ("provider_failure", "session_status", "expected_stage"),
    [(True, "completed", "tts"), (False, "failed", "playback")],
)
def test_streaming_segment_failure_is_fail_fast_without_legacy_fallback(
    provider_failure, session_status, expected_stage
):
    provider = ControlledStreamingProvider(fail_stream_index=0 if provider_failure else None)
    sessions = [] if provider_failure else [ControlledStreamingSession(terminal_status=session_status)]
    controller = ControlledStreamingController(sessions)
    orchestrator = _orchestrator(
        provider,
        controller,
        lambda _text, *, on_chunk, cancel_event: (
            on_chunk("第一段会失败。第二段绝不能继续。")
            or "第一段会失败。第二段绝不能继续。"
        ),
    )

    result = orchestrator.run()

    assert result.success is False
    assert result.cancelled is False
    assert result.stage == expected_stage
    assert provider.stream_calls == ["第一段会失败。"]
    assert provider.legacy_calls == []
    assert orchestrator._streaming_playback_context is None
    assert orchestrator._current_streaming_session is None
    segment_states = result.diagnostics["trace"]["streaming_segments"]
    assert segment_states[0]["status"] == "failed"
    assert result.diagnostics["metrics"]["streaming_status"] == "failed"


def test_later_segment_provider_failure_replaces_prior_completed_turn_status():
    provider = ControlledStreamingProvider(fail_stream_index=1)
    orchestrator = _orchestrator(
        provider,
        ControlledStreamingController([ControlledStreamingSession()]),
        lambda _text, *, on_chunk, cancel_event: (
            on_chunk("第一段成功。第二段失败。第三段不执行。")
            or "第一段成功。第二段失败。第三段不执行。"
        ),
    )

    result = orchestrator.run()

    assert result.success is False
    assert result.stage == "tts"
    assert provider.stream_calls == ["第一段成功。", "第二段失败。"]
    assert result.diagnostics["metrics"]["streaming_status"] == "failed"
    assert [item["status"] for item in result.diagnostics["trace"]["streaming_segments"]] == [
        "completed",
        "failed",
        "stale",
    ]


def test_late_old_generation_cancel_cannot_cancel_new_streaming_owner():
    provider = ControlledStreamingProvider()
    controller = ControlledStreamingController()
    orchestrator = _orchestrator(provider, controller, _one_sentence_handler)
    new_session = ControlledStreamingSession()
    new_segment = SpeechSegment("session-new", "generation-new", 0, "新请求。")
    orchestrator.set_generation_context("session-new", "generation-new")
    orchestrator._streaming_playback_context = (new_segment, new_session)
    orchestrator._current_streaming_session = new_session

    orchestrator._safe_cancel_runtime("session-old", "generation-old")

    assert new_session.cancel_calls == 0
    assert orchestrator._streaming_playback_context == (new_segment, new_session)
