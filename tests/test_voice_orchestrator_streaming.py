from threading import Event, Thread

from modules.experience.audio import (
    FakePlayback,
    FakeRecorder,
    StreamingPlaybackReport,
)
from modules.experience.state import CompanionState, CompanionStateStore
from modules.experience.voice.fake import FakeSpeechToTextProvider
from modules.experience.voice.interfaces import StreamingTTSProvider, TTSProvider
from modules.experience.voice.integration import create_voice_runtime
from modules.experience.voice.models import (
    AudioInput,
    SpeechResult,
    StreamingSpeechResult,
    TranscriptionResult,
    VoiceOptions,
)
from modules.experience.voice.orchestrator import VoiceOrchestrator
from modules.experience.voice.providers.edge_tts import EdgeTTSProvider
from modules.experience.voice.runtime import RuntimeService
from modules.experience.voice.tts_router import TTSRouter


def playback_report(status="completed", *, producer_error="", playback_error=""):
    return StreamingPlaybackReport(
        status=status,
        diagnostics={
            "success": status == "completed",
            "reason": status,
            "warnings": [],
            "metrics": {
                "request_to_first_audio_submission_ms": 25.0,
                "audio_duration_ms": 750.0,
                "sample_rate": 24000,
                "playback_start_monotonic": 10.0,
                "upstream_end_monotonic": 10.5,
                "playback_end_monotonic": 11.0,
                "underrun_count": 0,
                "buffer_peak_bytes": 12000,
                "cancel_latency_ms": 12.0 if status == "cancelled" else None,
                "producer_error": producer_error,
                "playback_error": playback_error,
                "provider_close_error": "",
            },
        },
    )


class FakeStreamingProvider(TTSProvider, StreamingTTSProvider):
    def __init__(self, *, stream_diagnostics=None, metadata=None):
        self.synthesize_calls = []
        self.stream_calls = []
        self.stream_close_calls = 0
        self.stream_diagnostics = stream_diagnostics or {
            "success": True,
            "reason": "stream_open",
        }
        self.metadata = metadata if metadata is not None else {
            "sample_format": "s16le",
            "bits_per_sample": 16,
            "sample_rate": 24000,
            "channels": 1,
            "interleaved": True,
        }

    def synthesize(
        self,
        text,
        options=None,
        *,
        timeout_seconds=None,
        cancel_event=None,
    ):
        self.synthesize_calls.append((text, options, timeout_seconds, cancel_event))
        return SpeechResult(audio_bytes=b"legacy", diagnostics={"success": True})

    def synthesize_stream(
        self,
        text,
        options=None,
        *,
        timeout_seconds=None,
        cancel_event=None,
    ):
        self.stream_calls.append((text, options, timeout_seconds, cancel_event))
        return StreamingSpeechResult(
            metadata=self.metadata,
            chunks=iter((b"\0\0",)),
            diagnostics=dict(self.stream_diagnostics),
            _close=self._close_stream,
        )

    def _close_stream(self):
        self.stream_close_calls += 1


class LegacyProvider(TTSProvider):
    def __init__(self):
        self.synthesize_calls = []

    def synthesize(
        self,
        text,
        options=None,
        *,
        timeout_seconds=None,
        cancel_event=None,
    ):
        self.synthesize_calls.append((text, options, timeout_seconds, cancel_event))
        return SpeechResult(audio_bytes=b"legacy", diagnostics={"success": True})


class TrackingEdgeProvider(EdgeTTSProvider):
    def __init__(self):
        super().__init__()
        self.synthesize_calls = 0

    def synthesize(self, *_args, **_kwargs):
        self.synthesize_calls += 1
        return SpeechResult(audio_bytes=b"edge", diagnostics={"success": True})


class FakeStreamingSession:
    def __init__(self, report=None, *, block_until_cancel=False):
        self.report = report or playback_report()
        self.block_until_cancel = block_until_cancel
        self.wait_started = Event()
        self.cancelled = Event()
        self.cancel_calls = 0

    def wait(self, _timeout=None):
        self.wait_started.set()
        if self.block_until_cancel:
            assert self.cancelled.wait(2)
            return playback_report("cancelled")
        return self.report

    def cancel(self):
        self.cancel_calls += 1
        self.cancelled.set()


class FakeStreamingController:
    def __init__(self, sessions=None):
        self.sessions = list(sessions or [FakeStreamingSession()])
        self.play_calls = []

    def play(self, speech, **timings):
        self.play_calls.append((speech, timings))
        return self.sessions.pop(0)


def build_orchestrator(provider, *, controller=None, streaming_enabled=True):
    return VoiceOrchestrator(
        recorder=FakeRecorder(AudioInput(kind="bytes", data=b"input")),
        stt_provider=FakeSpeechToTextProvider(TranscriptionResult(text="hello")),
        tts_provider=provider,
        playback=FakePlayback(auto_complete=True),
        state_store=CompanionStateStore(),
        text_input_handler=lambda _text: "Aurora streaming reply",
        wait_for_playback_completion=True,
        playback_timeout_seconds=2,
        streaming_enabled=streaming_enabled,
        streaming_playback=controller,
    )


def test_enabled_router_with_streaming_provider_uses_stream_path_and_cleans_up():
    provider = FakeStreamingProvider()
    controller = FakeStreamingController()
    router = TTSRouter({"third_party_stream": provider}, default_provider="third_party_stream")
    orchestrator = build_orchestrator(router, controller=controller)
    states = []
    orchestrator.state_store.subscribe(lambda event: states.append(event.current_state))

    result = orchestrator.run()

    assert result.success is True
    assert provider.stream_calls and provider.synthesize_calls == []
    assert len(controller.play_calls) == 1
    assert states[-2:] == [CompanionState.SPEAKING, CompanionState.IDLE]
    assert orchestrator._current_streaming_session is None
    metrics = result.diagnostics["metrics"]
    assert metrics["streaming_selected"] is True
    assert metrics["streaming_status"] == "completed"
    assert metrics["tts_provider"] == "FakeStreamingProvider"
    assert metrics["streaming_request_to_first_audio_submission_ms"] == 25.0
    assert metrics["streaming_underrun_count"] == 0
    assert metrics["audio_duration_ms"] == 750.0
    assert metrics["sample_rate"] == 24000
    assert result.diagnostics["trace"]["streaming_playback"]["reason"] == "completed"


def test_enabled_legacy_provider_uses_complete_path_without_provider_changes():
    provider = LegacyProvider()
    controller = FakeStreamingController()
    orchestrator = build_orchestrator(provider, controller=controller)

    result = orchestrator.run()

    assert result.success is True
    assert len(provider.synthesize_calls) == 1
    assert controller.play_calls == []
    assert len(orchestrator.playback.played) == 1
    assert result.diagnostics["metrics"]["streaming_selected"] is False
    assert result.diagnostics["metrics"]["audio_duration_ms"] == 0
    assert result.diagnostics["metrics"]["sample_rate"] is None


def test_disabled_streaming_provider_uses_complete_path():
    provider = FakeStreamingProvider()
    controller = FakeStreamingController()
    orchestrator = build_orchestrator(
        provider, controller=controller, streaming_enabled=False
    )

    result = orchestrator.run()

    assert result.success is True
    assert len(provider.synthesize_calls) == 1
    assert provider.stream_calls == []
    assert controller.play_calls == []


def test_edge_tts_remains_on_legacy_complete_path():
    provider = TrackingEdgeProvider()
    orchestrator = build_orchestrator(
        provider, controller=FakeStreamingController(), streaming_enabled=True
    )

    result = orchestrator.run()

    assert result.success is True
    assert provider.synthesize_calls == 1
    assert len(orchestrator.playback.played) == 1


def test_streaming_enabled_without_playback_capability_uses_complete_path():
    provider = FakeStreamingProvider()
    orchestrator = build_orchestrator(provider, controller=None)

    result = orchestrator.run()

    assert result.success is True
    assert len(provider.synthesize_calls) == 1
    assert provider.stream_calls == []


def test_streaming_cancel_stops_session_and_clears_owner():
    provider = FakeStreamingProvider()
    session = FakeStreamingSession(block_until_cancel=True)
    orchestrator = build_orchestrator(
        provider, controller=FakeStreamingController([session])
    )
    results = []
    thread = Thread(target=lambda: results.append(orchestrator.run()), daemon=True)
    thread.start()
    assert session.wait_started.wait(1)

    orchestrator.cancel()
    thread.join(2)

    assert not thread.is_alive()
    assert session.cancel_calls >= 1
    assert results[0].cancelled is True
    assert results[0].stage == "cancelled"
    assert results[0].diagnostics["metrics"]["streaming_status"] == "cancelled"
    assert orchestrator._current_streaming_session is None
    assert orchestrator.state_store.current_state is CompanionState.IDLE


def test_streaming_upstream_failure_is_tts_failure_and_cleans_up():
    provider = FakeStreamingProvider()
    session = FakeStreamingSession(
        playback_report("failed", producer_error="upstream X")
    )
    orchestrator = build_orchestrator(
        provider, controller=FakeStreamingController([session])
    )

    result = orchestrator.run()

    assert result.success is False
    assert result.stage == "tts"
    assert "upstream X" in result.diagnostics["reason"]
    assert orchestrator._current_streaming_session is None
    assert orchestrator.state_store.current_state is CompanionState.IDLE


def test_streaming_playback_failure_is_playback_failure_and_cleans_up():
    provider = FakeStreamingProvider()
    session = FakeStreamingSession(
        playback_report("failed", playback_error="speaker unavailable")
    )
    orchestrator = build_orchestrator(
        provider, controller=FakeStreamingController([session])
    )

    result = orchestrator.run()

    assert result.success is False
    assert result.stage == "playback"
    assert "speaker unavailable" in result.diagnostics["reason"]
    assert orchestrator._current_streaming_session is None


def test_stream_creation_failure_closes_result_before_playback():
    provider = FakeStreamingProvider(
        stream_diagnostics={"success": False, "reason": "metadata_failed"},
        metadata={},
    )
    controller = FakeStreamingController()
    orchestrator = build_orchestrator(provider, controller=controller)

    result = orchestrator.run()

    assert result.success is False
    assert result.stage == "tts"
    assert "metadata_failed" in result.diagnostics["reason"]
    assert provider.stream_close_calls == 1
    assert controller.play_calls == []
    assert orchestrator._current_streaming_session is None


def test_cancel_before_stream_metadata_returns_cancelled_without_playback():
    started = Event()

    class MetadataBlockingProvider(FakeStreamingProvider):
        def synthesize_stream(
            self,
            text,
            options=None,
            *,
            timeout_seconds=None,
            cancel_event=None,
        ):
            self.stream_calls.append((text, options, timeout_seconds, cancel_event))
            started.set()
            assert cancel_event.wait(2)
            return StreamingSpeechResult(
                metadata={},
                chunks=iter(()),
                diagnostics={"success": False, "reason": "cancelled"},
                _close=self._close_stream,
            )

    provider = MetadataBlockingProvider()
    controller = FakeStreamingController()
    orchestrator = build_orchestrator(provider, controller=controller)
    results = []
    thread = Thread(target=lambda: results.append(orchestrator.run()), daemon=True)
    thread.start()
    assert started.wait(1)

    orchestrator.cancel()
    thread.join(2)

    assert not thread.is_alive()
    assert results[0].cancelled is True
    assert results[0].diagnostics["metrics"]["streaming_status"] == "cancelled"
    assert provider.stream_close_calls == 1
    assert controller.play_calls == []
    assert orchestrator._current_streaming_session is None


def test_two_completed_runs_reuse_controller_without_stale_session():
    provider = FakeStreamingProvider()
    sessions = [FakeStreamingSession(), FakeStreamingSession()]
    controller = FakeStreamingController(sessions)
    orchestrator = build_orchestrator(provider, controller=controller)

    first = orchestrator.run()
    second = orchestrator.run()

    assert first.success is True and second.success is True
    assert len(provider.stream_calls) == 2
    assert len(controller.play_calls) == 2
    assert orchestrator._current_streaming_session is None


def test_streaming_controller_receives_timeout_and_metadata_timings():
    provider = FakeStreamingProvider()
    controller = FakeStreamingController()
    orchestrator = build_orchestrator(provider, controller=controller)

    result = orchestrator.run()

    assert result.success is True
    assert provider.stream_calls[0][2] == orchestrator.tts_timeout_seconds
    assert provider.stream_calls[0][3] is orchestrator._cancel_requested
    timings = controller.play_calls[0][1]
    assert timings["provider_metadata_monotonic"] >= timings["request_start_monotonic"]


def test_runtime_stop_during_streaming_cancels_owned_session():
    provider = FakeStreamingProvider()
    session = FakeStreamingSession(block_until_cancel=True)
    orchestrator = build_orchestrator(
        provider, controller=FakeStreamingController([session])
    )
    runtime = RuntimeService(orchestrator)
    assert runtime.start_voice_session() is True
    assert session.wait_started.wait(1)

    assert runtime.cancel_voice_session() is True
    result = runtime.wait_for_session(2)

    assert result is not None and result.cancelled is True
    assert session.cancel_calls >= 1
    assert orchestrator._current_streaming_session is None
    assert runtime.close() is True


def test_runtime_shutdown_during_streaming_leaves_no_current_session():
    provider = FakeStreamingProvider()
    session = FakeStreamingSession(block_until_cancel=True)
    orchestrator = build_orchestrator(
        provider, controller=FakeStreamingController([session])
    )
    runtime = RuntimeService(orchestrator)
    assert runtime.start_voice_session() is True
    assert session.wait_started.wait(1)

    assert runtime.close() is True

    assert session.cancel_calls >= 1
    assert orchestrator._current_streaming_session is None
    assert runtime.session_running is False


def test_llm_sentence_queue_keeps_existing_complete_tts_path():
    provider = FakeStreamingProvider()

    def stream_handler(_text, *, on_chunk, cancel_event):
        assert cancel_event.is_set() is False
        on_chunk("仍然使用现有完整 TTS。")
        return "仍然使用现有完整 TTS。"

    orchestrator = build_orchestrator(
        provider, controller=FakeStreamingController(), streaming_enabled=True
    )
    orchestrator.stream_text_input_handler = stream_handler

    result = orchestrator.run()

    assert result.success is True
    assert len(provider.synthesize_calls) == 1
    assert provider.stream_calls == []
    assert result.diagnostics["metrics"]["streaming_selected"] is False


def test_runtime_can_start_new_streaming_request_after_cancel():
    provider = FakeStreamingProvider()
    cancelled_session = FakeStreamingSession(block_until_cancel=True)
    controller = FakeStreamingController(
        [cancelled_session, FakeStreamingSession()]
    )
    settings = {
        "voice": {
            "enabled": True,
            "tts": {"provider": "fake", "streaming_enabled": True},
            "playback": {
                "backend": "pygame",
                "wait_for_completion": True,
                "timeout_seconds": 2,
            },
        }
    }
    runtime = create_voice_runtime(
        settings,
        recorder=FakeRecorder(AudioInput(kind="bytes", data=b"input")),
        text_input_handler=lambda _text: "reply",
        stt_provider=FakeSpeechToTextProvider(TranscriptionResult(text="hello")),
        tts_provider=provider,
        playback=FakePlayback(auto_complete=True),
        streaming_playback=controller,
    )
    assert runtime is not None
    assert runtime.start_voice_session() is True
    assert cancelled_session.wait_started.wait(1)
    assert runtime.cancel_voice_session() is True
    first = runtime.wait_for_session(2)

    assert first is not None and first.cancelled is True
    assert runtime.start_voice_session() is True
    second = runtime.wait_for_session(2)

    assert second is not None and second.success is True
    assert len(provider.stream_calls) == 2
    assert runtime.orchestrator._current_streaming_session is None
    assert runtime.close() is True
