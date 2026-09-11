import time
from threading import Event, Thread, current_thread

import pytest

from modules.experience.audio import (
    SoundDeviceOutputFactory,
    StreamingPlaybackController,
    StreamingPlaybackError,
)
from modules.experience.audio.streaming_playback import _wait_event_interruptibly
from modules.experience.voice.models import StreamingSpeechResult


def metadata(*, sample_rate=1000, channels=1):
    return {
        "sample_format": "s16le",
        "bits_per_sample": 16,
        "sample_rate": sample_rate,
        "channels": channels,
        "interleaved": True,
    }


def streaming_result(
    chunks=(),
    *,
    error=None,
    completed=True,
    close=None,
    before_finish=None,
):
    diagnostics = {"success": True, "reason": "stream_open", "metrics": {}}

    def iterator():
        for chunk in chunks:
            if callable(chunk):
                chunk = chunk()
            yield chunk
        if error is not None:
            raise error
        if before_finish is not None:
            before_finish()
        if completed:
            diagnostics["success"] = True
            diagnostics["reason"] = "stream_completed"

    return StreamingSpeechResult(
        metadata=metadata(),
        chunks=iterator(),
        diagnostics=diagnostics,
        _close=close or (lambda: None),
    )


class FakeStatus:
    def __init__(self, *, output_underflow=False):
        self.output_underflow = output_underflow


class FakeRawOutput:
    def __init__(
        self,
        callback,
        *,
        channels,
        frames=4,
        interval=0.001,
        bad_buffer=False,
        status=None,
    ):
        self.callback = callback
        self.channels = channels
        self.frames = frames
        self.interval = interval
        self.bad_buffer = bad_buffer
        self.status = status or FakeStatus()
        self.blocks = []
        self.started = Event()
        self.finished = Event()
        self.aborted = Event()
        self.closed = False
        self.thread = None

    def start(self):
        self.started.set()
        self.thread = Thread(target=self._run, name="fake-raw-output", daemon=True)
        self.thread.start()

    def _run(self):
        try:
            while not self.aborted.is_set():
                size = self.frames * self.channels * 2
                if self.bad_buffer:
                    size -= 1
                    self.bad_buffer = False
                output = bytearray(size)
                keep_running = self.callback(
                    memoryview(output), self.frames, self.status
                )
                self.blocks.append(bytes(output))
                if not keep_running:
                    return
                if self.interval:
                    time.sleep(self.interval)
        finally:
            self.finished.set()

    def wait(self, timeout=None):
        return self.finished.wait(timeout)

    def abort(self):
        self.aborted.set()
        self.finished.set()

    def close(self):
        self.closed = True
        if self.thread is not None and self.thread is not current_thread():
            self.thread.join(1)


class FakeOutputFactory:
    def __init__(
        self,
        *,
        frames=4,
        interval=0.001,
        open_error=None,
        bad_buffer=False,
        status=None,
    ):
        self.frames = frames
        self.interval = interval
        self.open_error = open_error
        self.bad_buffer = bad_buffer
        self.status = status
        self.calls = []
        self.outputs = []

    def open(self, *, sample_rate, channels, device, callback):
        self.calls.append(
            {
                "sample_rate": sample_rate,
                "channels": channels,
                "device": device,
            }
        )
        if self.open_error is not None:
            raise self.open_error
        output = FakeRawOutput(
            callback,
            channels=channels,
            frames=self.frames,
            interval=self.interval,
            bad_buffer=self.bad_buffer,
            status=self.status,
        )
        self.outputs.append(output)
        return output


def run_playback(
    result,
    *,
    factory=None,
    prebuffer_ms=250,
    max_buffer_ms=2000,
    device=None,
):
    factory = factory or FakeOutputFactory()
    controller = StreamingPlaybackController(
        output_factory=factory,
        prebuffer_ms=prebuffer_ms,
        max_buffer_ms=max_buffer_ms,
        device=device,
        close_timeout_seconds=1,
    )
    session = controller.play(result)
    report = session.wait(3)
    return session, report, factory


def test_rejects_unsupported_metadata_without_opening_audio_device():
    result = streaming_result([b"\0\0"])
    result.metadata = {**metadata(), "sample_format": "f32le"}
    factory = FakeOutputFactory()
    controller = StreamingPlaybackController(output_factory=factory)

    with pytest.raises(StreamingPlaybackError, match="s16le"):
        controller.play(result)

    assert factory.calls == []


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("bits_per_sample", 24, "16-bit"),
        ("sample_rate", 0, "sample_rate"),
        ("channels", 0, "channels"),
        ("interleaved", False, "non-interleaved"),
    ],
)
def test_rejects_invalid_pcm_metadata(field, value, message):
    result = streaming_result([b"\0\0"])
    result.metadata = {**metadata(), field: value}

    with pytest.raises(StreamingPlaybackError, match=message):
        StreamingPlaybackController(output_factory=FakeOutputFactory()).play(result)


def test_normal_multi_chunk_playback_drains_after_upstream_end():
    audio = b"".join(bytes((value, 0)) * 4 for value in (1, 2, 3))
    session, report, factory = run_playback(
        streaming_result([audio[:5], audio[5:13], audio[13:]]),
        prebuffer_ms=250,
    )

    captured = b"".join(factory.outputs[0].blocks)
    metrics = report.diagnostics["metrics"]
    assert report.status == "completed"
    assert captured[: len(audio)] == audio
    assert metrics["received_pcm_bytes"] == len(audio)
    assert metrics["played_pcm_bytes"] == len(audio)
    assert metrics["upstream_end_monotonic"] <= metrics["playback_end_monotonic"]
    assert session.threads_alive() == ()


def test_prebuffer_threshold_is_calculated_from_metadata():
    audio = b"\1\0" * 40
    _session, report, factory = run_playback(
        streaming_result([audio[:20], audio[20:40], audio[40:]]),
        prebuffer_ms=20,
        max_buffer_ms=200,
        device="test-output",
    )

    metrics = report.diagnostics["metrics"]
    assert metrics["prebuffer_bytes"] == 40
    assert metrics["buffer_bytes_at_playback_start"] >= 40
    assert factory.calls[0] == {
        "sample_rate": 1000,
        "channels": 1,
        "device": "test-output",
    }


def test_default_buffer_sizes_are_dynamic_for_24khz_mono():
    result = streaming_result([b"\1\0" * 8])
    result.metadata = metadata(sample_rate=24000)
    _session, report, _factory = run_playback(result)

    metrics = report.diagnostics["metrics"]
    assert metrics["prebuffer_bytes"] == 12000
    assert metrics["max_buffer_bytes"] == 96000


def test_short_audio_below_prebuffer_still_plays():
    audio = b"\5\0" * 5
    _session, report, factory = run_playback(
        streaming_result([audio]),
        prebuffer_ms=250,
    )

    assert report.status == "completed"
    assert report.diagnostics["metrics"]["buffer_bytes_at_playback_start"] == len(audio)
    assert b"".join(factory.outputs[0].blocks)[: len(audio)] == audio


def test_fast_producer_observes_bounded_buffer_backpressure():
    audio = b"\7\0" * 200
    factory = FakeOutputFactory(frames=5, interval=0.01)
    _session, report, _factory = run_playback(
        streaming_result([audio]),
        factory=factory,
        prebuffer_ms=10,
        max_buffer_ms=20,
    )

    metrics = report.diagnostics["metrics"]
    assert report.status == "completed"
    assert metrics["buffer_peak_bytes"] <= metrics["max_buffer_bytes"] == 40
    assert metrics["producer_wait_count"] > 0
    assert metrics["played_pcm_bytes"] == len(audio)


def test_slow_producer_inserts_silence_without_repeating_old_pcm():
    first = b"\x11\x22" * 4
    second = b"\x33\x44" * 4

    def delayed_second():
        time.sleep(0.04)
        return second

    factory = FakeOutputFactory(frames=4, interval=0.005)
    _session, report, _factory = run_playback(
        streaming_result([first, delayed_second]),
        factory=factory,
        prebuffer_ms=4,
        max_buffer_ms=100,
    )

    captured = b"".join(factory.outputs[0].blocks)
    first_at = captured.find(first)
    second_at = captured.find(second)
    assert report.status == "completed"
    assert report.diagnostics["metrics"]["underrun_count"] > 0
    assert first_at == 0
    assert second_at > len(first)
    assert set(captured[len(first) : second_at]) <= {0}
    assert captured.count(first) == 1
    assert captured.count(second) == 1


def test_stereo_chunks_split_at_arbitrary_boundaries_remain_frame_aligned():
    audio = bytes(range(1, 17))
    result = streaming_result([audio[:1], audio[1:3], audio[3:8], audio[8:]])
    result.metadata = metadata(channels=2)
    factory = FakeOutputFactory(frames=2)

    _session, report, _factory = run_playback(
        result,
        factory=factory,
        prebuffer_ms=250,
    )

    assert report.status == "completed"
    assert report.diagnostics["metrics"]["frame_bytes"] == 4
    assert b"".join(factory.outputs[0].blocks)[: len(audio)] == audio


def test_final_dangling_byte_is_a_protocol_failure():
    result = streaming_result([b"\1\2\3\4\5"])
    result.metadata = metadata(channels=2)
    _session, report, _factory = run_playback(result)

    assert report.status == "failed"
    assert "dangling byte" in report.diagnostics["metrics"]["producer_error"]
    assert report.diagnostics["metrics"]["received_pcm_bytes"] == 4


def test_upstream_exception_before_audio_never_opens_output():
    factory = FakeOutputFactory()
    _session, report, _factory = run_playback(
        streaming_result(error=RuntimeError("upstream X"), completed=False),
        factory=factory,
    )

    assert report.status == "failed"
    assert report.diagnostics["metrics"]["producer_error"] == "upstream X"
    assert factory.outputs == []


def test_eof_without_confirmed_end_drains_audio_then_fails():
    audio = b"\6\0" * 8
    _session, report, factory = run_playback(
        streaming_result([audio], completed=False),
        prebuffer_ms=250,
    )

    assert report.status == "failed"
    assert report.diagnostics["metrics"]["played_pcm_bytes"] == len(audio)
    assert "confirmed END" in report.diagnostics["metrics"]["producer_error"]
    assert b"".join(factory.outputs[0].blocks)[: len(audio)] == audio


def test_audio_sink_open_exception_cancels_provider_and_fails():
    closed = Event()
    factory = FakeOutputFactory(open_error=RuntimeError("device unavailable"))
    _session, report, _factory = run_playback(
        streaming_result([b"\1\0" * 8], close=closed.set),
        factory=factory,
    )

    assert report.status == "failed"
    assert report.diagnostics["metrics"]["playback_error"] == "device unavailable"
    assert closed.is_set()


def test_audio_callback_failure_stops_producer_and_fails():
    factory = FakeOutputFactory(bad_buffer=True)
    session, report, _factory = run_playback(
        streaming_result([b"\1\0" * 8]),
        factory=factory,
        prebuffer_ms=4,
    )

    assert report.status == "failed"
    assert "buffer size mismatch" in report.diagnostics["metrics"]["playback_error"]
    assert session.threads_alive() == ()


def test_cancel_before_first_audio_closes_provider_without_opening_device():
    entered = Event()
    released = Event()
    closed = Event()
    diagnostics = {"success": True, "reason": "stream_open", "metrics": {}}

    def chunks():
        entered.set()
        released.wait(2)
        if closed.is_set():
            raise RuntimeError("response closed")
        yield b"\1\0"

    def close():
        closed.set()
        released.set()

    result = StreamingSpeechResult(metadata(), chunks(), diagnostics, close)
    factory = FakeOutputFactory()
    controller = StreamingPlaybackController(
        output_factory=factory, close_timeout_seconds=1
    )
    session = controller.play(result)
    assert entered.wait(1)

    session.cancel()
    report = session.wait(1)

    assert report.status == "cancelled"
    assert closed.is_set()
    assert factory.outputs == []
    assert session.threads_alive() == ()


def test_cancel_during_prebuffer_discards_partial_audio_without_opening_device():
    waiting = Event()
    released = Event()
    closed = Event()
    diagnostics = {"success": True, "reason": "stream_open", "metrics": {}}

    def chunks():
        yield b"\1\0" * 2
        waiting.set()
        released.wait(2)
        if closed.is_set():
            raise RuntimeError("response closed")

    def close():
        closed.set()
        released.set()

    result = StreamingSpeechResult(metadata(), chunks(), diagnostics, close)
    factory = FakeOutputFactory()
    controller = StreamingPlaybackController(
        output_factory=factory,
        prebuffer_ms=100,
        max_buffer_ms=200,
        close_timeout_seconds=1,
    )
    session = controller.play(result)
    assert waiting.wait(1)

    session.cancel()
    report = session.wait(1)
    metrics = report.diagnostics["metrics"]

    assert report.status == "cancelled"
    assert metrics["cancel_discarded_pcm_bytes"] == 4
    assert metrics["provider_closed"] is True
    assert metrics["audio_stream_stopped"] is True
    assert factory.outputs == []
    assert session.threads_alive() == ()


def test_cancel_during_playback_closes_stream_and_all_threads():
    waiting = Event()
    released = Event()
    closed = Event()
    diagnostics = {"success": True, "reason": "stream_open", "metrics": {}}

    def chunks():
        yield b"\1\0" * 20
        waiting.set()
        released.wait(2)
        if closed.is_set():
            raise RuntimeError("response closed")
        yield b"\2\0" * 20

    def close():
        closed.set()
        released.set()

    result = StreamingSpeechResult(metadata(), chunks(), diagnostics, close)
    factory = FakeOutputFactory(frames=2, interval=0.01)
    controller = StreamingPlaybackController(
        output_factory=factory,
        prebuffer_ms=4,
        max_buffer_ms=20,
        close_timeout_seconds=1,
    )
    session = controller.play(result)
    assert waiting.wait(1)
    assert factory.outputs[0].started.wait(1)

    session.cancel()
    report = session.wait(1)

    assert report.status == "cancelled"
    assert closed.is_set()
    assert factory.outputs[0].aborted.is_set()
    assert report.diagnostics["metrics"]["cancel_latency_ms"] is not None
    assert report.diagnostics["metrics"]["provider_closed"] is True
    assert report.diagnostics["metrics"]["audio_stream_stopped"] is True
    assert session.threads_alive() == ()


def test_cancel_socket_shutdown_incomplete_stream_remains_cancelled():
    waiting = Event()
    socket_closed = Event()
    diagnostics = {"success": True, "reason": "stream_open", "metrics": {}}

    def chunks():
        yield b"\1\0" * 20
        waiting.set()
        socket_closed.wait(2)
        raise RuntimeError("cosyvoice-server returned an incomplete PCM stream")

    result = StreamingSpeechResult(
        metadata(), chunks(), diagnostics, socket_closed.set
    )
    factory = FakeOutputFactory(frames=2, interval=0.01)
    controller = StreamingPlaybackController(
        output_factory=factory,
        prebuffer_ms=4,
        max_buffer_ms=100,
        close_timeout_seconds=1,
    )
    session = controller.play(result)
    assert waiting.wait(1)
    assert factory.outputs[0].started.wait(1)

    session.cancel()
    report = session.wait(1)
    metrics = report.diagnostics["metrics"]

    assert report.status == "cancelled"
    assert metrics["cancel_requested_monotonic"] is not None
    assert metrics["cancel_completed_monotonic"] is not None
    assert metrics["cancel_latency_ms"] >= 0
    assert metrics["producer_error"] == ""
    assert metrics["provider_closed"] is True
    assert metrics["audio_stream_stopped"] is True
    assert session.threads_alive() == ()


def test_cancel_while_callback_underruns_stops_silence_callbacks():
    waiting = Event()
    socket_closed = Event()
    diagnostics = {"success": True, "reason": "stream_open", "metrics": {}}

    def chunks():
        yield b"\1\0" * 2
        waiting.set()
        socket_closed.wait(2)
        raise RuntimeError("incomplete PCM stream")

    result = StreamingSpeechResult(
        metadata(), chunks(), diagnostics, socket_closed.set
    )
    factory = FakeOutputFactory(frames=2, interval=0.001)
    controller = StreamingPlaybackController(
        output_factory=factory,
        prebuffer_ms=2,
        max_buffer_ms=20,
        close_timeout_seconds=1,
    )
    session = controller.play(result)
    assert waiting.wait(1)
    output = factory.outputs[0]
    deadline = time.monotonic() + 1
    while (
        session.diagnostics_snapshot()["metrics"]["underrun_count"] < 3
        and time.monotonic() < deadline
    ):
        time.sleep(0.002)

    session.cancel()
    report = session.wait(1)
    blocks_after_cancel = len(output.blocks)
    time.sleep(0.03)

    assert report.status == "cancelled"
    assert output.aborted.is_set()
    assert len(output.blocks) == blocks_after_cancel
    assert report.diagnostics["metrics"]["underrun_count"] >= 3
    assert session.threads_alive() == ()


def test_interruptible_event_wait_propagates_first_keyboard_interrupt():
    class InterruptingEvent:
        def __init__(self):
            self.wait_calls = []

        def is_set(self):
            return False

        def wait(self, timeout):
            self.wait_calls.append(timeout)
            raise KeyboardInterrupt

    event = InterruptingEvent()

    with pytest.raises(KeyboardInterrupt):
        _wait_event_interruptibly(event, 300)

    assert len(event.wait_calls) == 1
    assert 0 < event.wait_calls[0] <= 0.05


def test_cancel_aborts_audio_before_waiting_for_provider_close():
    waiting = Event()
    close_entered = Event()
    release_close = Event()
    release_network = Event()
    diagnostics = {"success": True, "reason": "stream_open", "metrics": {}}

    def chunks():
        yield b"\1\0" * 40
        waiting.set()
        release_network.wait(2)
        raise RuntimeError("response closed")

    def close():
        close_entered.set()
        release_close.wait(2)
        release_network.set()

    result = StreamingSpeechResult(metadata(), chunks(), diagnostics, close)
    factory = FakeOutputFactory(frames=2, interval=0.01)
    controller = StreamingPlaybackController(
        output_factory=factory,
        prebuffer_ms=4,
        max_buffer_ms=100,
        close_timeout_seconds=1,
    )
    session = controller.play(result)
    assert waiting.wait(1)
    assert factory.outputs[0].started.wait(1)

    cancel_thread = Thread(target=session.cancel)
    cancel_thread.start()
    assert close_entered.wait(1)
    assert factory.outputs[0].aborted.is_set()
    release_close.set()
    cancel_thread.join(2)
    report = session.wait(1)

    assert cancel_thread.is_alive() is False
    assert report.status == "cancelled"
    assert session.threads_alive() == ()


def test_cancel_wakes_producer_blocked_on_full_buffer_and_is_idempotent():
    class PassiveOutput:
        def __init__(self):
            self.started = Event()
            self.finished = Event()
            self.aborted = Event()
            self.closed = False

        def start(self):
            self.started.set()

        def wait(self, timeout=None):
            return self.finished.wait(timeout)

        def abort(self):
            self.aborted.set()
            self.finished.set()

        def close(self):
            self.closed = True
            self.finished.set()

    class PassiveFactory:
        def __init__(self):
            self.output = PassiveOutput()

        def open(self, **_kwargs):
            return self.output

    close_calls = []
    result = streaming_result(
        [b"\1\0" * 1000], close=lambda: close_calls.append(True)
    )
    factory = PassiveFactory()
    controller = StreamingPlaybackController(
        output_factory=factory,
        prebuffer_ms=4,
        max_buffer_ms=20,
        close_timeout_seconds=1,
    )
    session = controller.play(result)
    assert factory.output.started.wait(1)
    deadline = time.monotonic() + 1
    while (
        session.diagnostics_snapshot()["metrics"]["producer_wait_count"] == 0
        and time.monotonic() < deadline
    ):
        time.sleep(0.005)

    session.cancel()
    session.cancel()
    session.close()
    report = session.wait(1)

    assert report.status == "cancelled"
    assert factory.output.aborted.is_set()
    assert factory.output.closed is True
    assert len(close_calls) == 1
    assert session.threads_alive() == ()


def test_cancel_while_output_is_opening_never_starts_audio_after_cancel():
    open_entered = Event()
    release_open = Event()

    class DelayedOutput:
        def __init__(self):
            self.start_calls = 0
            self.closed = False

        def start(self):
            self.start_calls += 1

        def wait(self, _timeout=None):
            return False

        def abort(self):
            return None

        def close(self):
            self.closed = True

    class DelayedFactory:
        def __init__(self):
            self.output = DelayedOutput()

        def open(self, **_kwargs):
            open_entered.set()
            release_open.wait(2)
            return self.output

    factory = DelayedFactory()
    controller = StreamingPlaybackController(
        output_factory=factory,
        prebuffer_ms=4,
        close_timeout_seconds=1,
    )
    session = controller.play(streaming_result([b"\1\0" * 8]))
    assert open_entered.wait(1)

    cancel_thread = Thread(target=session.cancel)
    cancel_thread.start()
    release_open.set()
    cancel_thread.join(2)
    report = session.wait(1)

    assert report.status == "cancelled"
    assert factory.output.start_calls == 0
    assert factory.output.closed is True
    assert session.audio_stream_stopped is True
    assert session.threads_alive() == ()


def test_zero_audio_is_failed_without_opening_output():
    factory = FakeOutputFactory()
    _session, report, _factory = run_playback(
        streaming_result([]), factory=factory
    )

    assert report.status == "failed"
    assert "without audio" in report.diagnostics["metrics"]["producer_error"]
    assert factory.outputs == []


def test_close_is_idempotent_after_completion():
    session, report, _factory = run_playback(streaming_result([b"\1\0" * 4]))

    session.close()
    session.close()

    assert report.status == "completed"
    assert session.wait(1).status == "completed"


def test_report_records_first_submission_and_device_underflow():
    factory = FakeOutputFactory(status=FakeStatus(output_underflow=True))
    request_start = time.monotonic()
    controller = StreamingPlaybackController(
        output_factory=factory,
        prebuffer_ms=250,
        close_timeout_seconds=1,
    )
    result = streaming_result([b"\1\0" * 4])
    metadata_time = time.monotonic()
    report = controller.play(
        result,
        request_start_monotonic=request_start,
        provider_metadata_monotonic=metadata_time,
    ).wait(2)
    metrics = report.diagnostics["metrics"]

    assert report.status == "completed"
    assert metrics["first_pcm_received_monotonic"] is not None
    assert metrics["first_audio_submission_monotonic"] is not None
    assert metrics["request_to_first_audio_submission_ms"] >= 0
    assert metrics["device_underflow_count"] >= 1
    assert metrics["underrun_count"] >= 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"prebuffer_ms": float("nan")},
        {"max_buffer_ms": float("inf")},
        {"close_timeout_seconds": 0},
    ],
)
def test_controller_rejects_non_finite_or_invalid_limits(kwargs):
    with pytest.raises(ValueError):
        StreamingPlaybackController(output_factory=FakeOutputFactory(), **kwargs)


def test_sounddevice_factory_uses_raw_int16_stream_and_callback_stop():
    class CallbackStop(Exception):
        pass

    class Backend:
        def __init__(self):
            self.kwargs = None

        def RawOutputStream(self, **kwargs):
            self.kwargs = kwargs
            return self

        def start(self):
            return None

        def abort(self):
            return None

        def close(self):
            return None

    Backend.CallbackStop = CallbackStop
    backend = Backend()
    factory = SoundDeviceOutputFactory(backend)
    output = factory.open(
        sample_rate=24000,
        channels=1,
        device=3,
        callback=lambda _out, _frames, _status: False,
    )

    assert backend.kwargs["samplerate"] == 24000
    assert backend.kwargs["channels"] == 1
    assert backend.kwargs["dtype"] == "int16"
    assert backend.kwargs["device"] == 3
    with pytest.raises(CallbackStop):
        backend.kwargs["callback"](bytearray(8), 4, None, FakeStatus())
    backend.kwargs["finished_callback"]()
    assert output.wait(0.1) is True
