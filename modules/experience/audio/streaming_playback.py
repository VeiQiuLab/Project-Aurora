"""Bounded raw-PCM playback for streaming TTS results."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from math import ceil, isfinite
from threading import Condition, Event, Lock, Thread, current_thread
from time import monotonic
from typing import Any, Callable, Mapping, Protocol

from modules.diagnostics import create_diagnostics
from modules.experience.voice.models import StreamingSpeechResult


class StreamingPlaybackError(RuntimeError):
    """A streaming result cannot be played by the PCM output boundary."""


@dataclass(frozen=True)
class StreamingPlaybackReport:
    """Terminal state and diagnostics for one streaming playback session."""

    status: str
    diagnostics: Mapping[str, object]

    @property
    def success(self) -> bool:
        return self.status == "completed"


PcmCallback = Callable[[memoryview, int, object], bool]
_INTERRUPTIBLE_WAIT_SLICE_SECONDS = 0.05


class RawPcmOutput(Protocol):
    """Minimal output stream controlled by a playback session."""

    def start(self) -> None: ...

    def wait(self, timeout: float | None = None) -> bool: ...

    def abort(self) -> None: ...

    def close(self) -> None: ...


class RawPcmOutputFactory(Protocol):
    """Open a raw PCM device without exposing sounddevice to core logic."""

    def open(
        self,
        *,
        sample_rate: int,
        channels: int,
        device: object | None,
        callback: PcmCallback,
    ) -> RawPcmOutput: ...


class SoundDeviceOutputFactory:
    """Lazy sounddevice RawOutputStream factory used by real playback."""

    def __init__(self, audio_backend: Any | None = None) -> None:
        self._audio_backend = audio_backend

    def open(
        self,
        *,
        sample_rate: int,
        channels: int,
        device: object | None,
        callback: PcmCallback,
    ) -> RawPcmOutput:
        backend = self._backend()
        return _SoundDeviceRawOutput(
            backend,
            sample_rate=sample_rate,
            channels=channels,
            device=device,
            callback=callback,
        )

    def _backend(self) -> Any:
        if self._audio_backend is not None:
            return self._audio_backend
        try:
            import sounddevice
        except ImportError as error:
            raise StreamingPlaybackError(
                "sounddevice is required for streaming PCM playback"
            ) from error
        self._audio_backend = sounddevice
        return sounddevice


class _SoundDeviceRawOutput:
    def __init__(
        self,
        backend: Any,
        *,
        sample_rate: int,
        channels: int,
        device: object | None,
        callback: PcmCallback,
    ) -> None:
        self._backend = backend
        self._finished = Event()

        def on_audio(outdata: Any, frames: int, _time_info: Any, status: object) -> None:
            view = memoryview(outdata).cast("B")
            if not callback(view, int(frames), status):
                raise backend.CallbackStop

        self._stream = backend.RawOutputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype="int16",
            device=device,
            callback=on_audio,
            finished_callback=self._finished.set,
        )

    def start(self) -> None:
        self._stream.start()

    def wait(self, timeout: float | None = None) -> bool:
        return self._finished.wait(timeout)

    def abort(self) -> None:
        try:
            self._stream.abort()
        finally:
            self._finished.set()

    def close(self) -> None:
        try:
            self._stream.close()
        finally:
            self._finished.set()


class StreamingPlaybackController:
    """Start independent real-time playback for one streaming TTS result."""

    def __init__(
        self,
        *,
        output_factory: RawPcmOutputFactory | None = None,
        prebuffer_ms: float = 250.0,
        max_buffer_ms: float = 2000.0,
        device: object | None = None,
        close_timeout_seconds: float = 5.0,
    ) -> None:
        prebuffer_ms = float(prebuffer_ms)
        max_buffer_ms = float(max_buffer_ms)
        if not isfinite(prebuffer_ms) or not isfinite(max_buffer_ms):
            raise ValueError("buffer durations must be finite")
        if prebuffer_ms < 0:
            raise ValueError("prebuffer_ms must not be negative")
        if max_buffer_ms <= 0:
            raise ValueError("max_buffer_ms must be greater than zero")
        if prebuffer_ms > max_buffer_ms:
            raise ValueError("prebuffer_ms must not exceed max_buffer_ms")
        self.output_factory = (
            output_factory if output_factory is not None else SoundDeviceOutputFactory()
        )
        self.prebuffer_ms = prebuffer_ms
        self.max_buffer_ms = max_buffer_ms
        self.device = device
        close_timeout_seconds = float(close_timeout_seconds)
        if not isfinite(close_timeout_seconds) or close_timeout_seconds <= 0:
            raise ValueError("close_timeout_seconds must be finite and positive")
        self.close_timeout_seconds = close_timeout_seconds

    def play(
        self,
        speech: StreamingSpeechResult,
        *,
        request_start_monotonic: float | None = None,
        provider_metadata_monotonic: float | None = None,
    ) -> "StreamingPlaybackSession":
        if not isinstance(speech, StreamingSpeechResult):
            raise TypeError("speech must be a StreamingSpeechResult")
        audio_format = _validate_metadata(speech.metadata)
        session = StreamingPlaybackSession(
            speech,
            output_factory=self.output_factory,
            audio_format=audio_format,
            prebuffer_ms=self.prebuffer_ms,
            max_buffer_ms=self.max_buffer_ms,
            device=self.device,
            close_timeout_seconds=self.close_timeout_seconds,
            request_start_monotonic=request_start_monotonic,
            provider_metadata_monotonic=provider_metadata_monotonic,
        )
        session.start()
        return session


@dataclass(frozen=True)
class _PcmFormat:
    sample_rate: int
    channels: int

    @property
    def frame_bytes(self) -> int:
        return self.channels * 2

    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate * self.frame_bytes


class StreamingPlaybackSession:
    """Own producer, bounded buffer, output stream, and terminal report."""

    def __init__(
        self,
        speech: StreamingSpeechResult,
        *,
        output_factory: RawPcmOutputFactory,
        audio_format: _PcmFormat,
        prebuffer_ms: float,
        max_buffer_ms: float,
        device: object | None,
        close_timeout_seconds: float,
        request_start_monotonic: float | None,
        provider_metadata_monotonic: float | None,
    ) -> None:
        created = monotonic()
        self.speech = speech
        self.output_factory = output_factory
        self.audio_format = audio_format
        self.prebuffer_ms = prebuffer_ms
        self.max_buffer_ms = max_buffer_ms
        self.device = device
        self.close_timeout_seconds = close_timeout_seconds
        self.prebuffer_bytes = _milliseconds_to_bytes(
            prebuffer_ms, audio_format.bytes_per_second, audio_format.frame_bytes
        )
        self.max_buffer_bytes = _milliseconds_to_bytes(
            max_buffer_ms, audio_format.bytes_per_second, audio_format.frame_bytes
        )

        self._condition = Condition()
        self._buffer: deque[bytes] = deque()
        self._buffer_offset = 0
        self._buffer_bytes = 0
        self._upstream_done = False
        self._producer_error = ""
        self._playback_error = ""
        self._cancel_requested = Event()
        self._user_cancel_requested = Event()
        self._done = Event()
        self._provider_close_finished = Event()
        self._audio_stream_stopped = Event()
        self._close_lock = Lock()
        self._output_control_lock = Lock()
        self._result_closed = False
        self._finalize_lock = Lock()
        self._report: StreamingPlaybackReport | None = None
        self._output: RawPcmOutput | None = None
        self._output_started = False
        self._producer_thread = Thread(
            target=self._producer_main,
            name="aurora-streaming-pcm-producer",
            daemon=True,
        )
        self._manager_thread = Thread(
            target=self._manager_main,
            name="aurora-streaming-playback-manager",
            daemon=True,
        )
        self._started = False
        self._metrics: dict[str, object] = {
            "request_start_monotonic": (
                float(request_start_monotonic)
                if request_start_monotonic is not None
                else created
            ),
            "provider_metadata_monotonic": (
                float(provider_metadata_monotonic)
                if provider_metadata_monotonic is not None
                else created
            ),
            "first_pcm_received_monotonic": None,
            "playback_start_monotonic": None,
            "first_audio_submission_monotonic": None,
            "upstream_end_monotonic": None,
            "playback_end_monotonic": None,
            "sample_rate": audio_format.sample_rate,
            "channels": audio_format.channels,
            "frame_bytes": audio_format.frame_bytes,
            "prebuffer_ms": prebuffer_ms,
            "prebuffer_bytes": self.prebuffer_bytes,
            "max_buffer_ms": max_buffer_ms,
            "max_buffer_bytes": self.max_buffer_bytes,
            "buffer_bytes_at_playback_start": 0,
            "buffer_peak_bytes": 0,
            "buffer_low_watermark": None,
            "received_pcm_bytes": 0,
            "played_pcm_bytes": 0,
            "underrun_count": 0,
            "underrun_frames": 0,
            "device_underflow_count": 0,
            "producer_wait_count": 0,
            "producer_error": "",
            "playback_error": "",
            "provider_closed": False,
            "provider_close_error": "",
            "audio_stream_stopped": False,
            "cancel_discarded_pcm_bytes": 0,
            "cancel_requested_monotonic": None,
            "cancel_completed_monotonic": None,
            "cancel_latency_ms": None,
        }

    def start(self) -> None:
        with self._condition:
            if self._started:
                raise RuntimeError("streaming playback session is already started")
            self._started = True
        self._producer_thread.start()
        self._manager_thread.start()

    def wait(self, timeout: float | None = None) -> StreamingPlaybackReport:
        if not _wait_event_interruptibly(self._done, timeout):
            raise TimeoutError("streaming playback did not finish before the timeout")
        this_thread = current_thread()
        for thread in (self._producer_thread, self._manager_thread):
            if thread is not this_thread:
                _join_thread_interruptibly(thread, self.close_timeout_seconds)
        assert self._report is not None
        return self._report

    def cancel(self) -> None:
        if self._done.is_set():
            return
        with self._condition:
            first_request = not self._user_cancel_requested.is_set()
            if first_request:
                self._metrics["cancel_requested_monotonic"] = monotonic()
                self._metrics["cancel_discarded_pcm_bytes"] = self._buffer_bytes
            self._user_cancel_requested.set()
            self._cancel_requested.set()
            self._buffer.clear()
            self._buffer_offset = 0
            self._buffer_bytes = 0
            self._condition.notify_all()
        try:
            with self._output_control_lock:
                with self._condition:
                    output = self._output
                if output is not None:
                    if self._output_started:
                        output.abort()
                        self._output_started = False
                        self._audio_stream_stopped.set()
        except Exception as error:
            with self._condition:
                self._playback_error = str(error) or type(error).__name__
                self._metrics["playback_error"] = self._playback_error
        self._close_result_once()
        this_thread = current_thread()
        if this_thread not in {self._manager_thread, self._producer_thread}:
            _join_thread_interruptibly(self._manager_thread, self.close_timeout_seconds)
            _join_thread_interruptibly(self._producer_thread, self.close_timeout_seconds)

    close = cancel

    def is_running(self) -> bool:
        return self._started and not self._done.is_set()

    def threads_alive(self) -> tuple[str, ...]:
        threads = (self._producer_thread, self._manager_thread)
        return tuple(thread.name for thread in threads if thread.is_alive())

    @property
    def provider_closed(self) -> bool:
        return self._provider_close_finished.is_set() and not bool(
            self._metrics["provider_close_error"]
        )

    @property
    def audio_stream_stopped(self) -> bool:
        return self._audio_stream_stopped.is_set()

    def diagnostics_snapshot(self) -> Mapping[str, object]:
        with self._condition:
            metrics = deepcopy(self._metrics)
        return create_diagnostics(
            stage="experience.audio.streaming_playback",
            success=self._done.is_set() and bool(self._report and self._report.success),
            reason=self._report.status if self._report else "running",
            metrics=metrics,
        )

    def _producer_main(self) -> None:
        pending = bytearray()
        try:
            for chunk in self.speech.chunks:
                if self._cancel_requested.is_set():
                    raise _PlaybackCancelled
                if not isinstance(chunk, (bytes, bytearray, memoryview)):
                    raise StreamingPlaybackError("PCM chunks must be bytes-like")
                data = bytes(chunk)
                if not data:
                    continue
                now = monotonic()
                with self._condition:
                    if self._metrics["first_pcm_received_monotonic"] is None:
                        self._metrics["first_pcm_received_monotonic"] = now
                pending.extend(data)
                aligned = len(pending) - (len(pending) % self.audio_format.frame_bytes)
                if aligned:
                    ready = bytes(pending[:aligned])
                    del pending[:aligned]
                    with self._condition:
                        self._metrics["received_pcm_bytes"] = int(
                            self._metrics["received_pcm_bytes"]
                        ) + len(ready)
                    self._write_buffered(ready)
            if pending:
                raise StreamingPlaybackError(
                    f"PCM stream ended with {len(pending)} dangling byte(s)"
                )
            diagnostics = self.speech.diagnostics
            if diagnostics.get("success") is not True or diagnostics.get("reason") != "stream_completed":
                raise StreamingPlaybackError("PCM stream ended without a confirmed END frame")
            with self._condition:
                if int(self._metrics["received_pcm_bytes"]) == 0:
                    raise StreamingPlaybackError("PCM stream completed without audio")
        except _PlaybackCancelled:
            pass
        except Exception as error:
            with self._condition:
                if not self._cancel_requested.is_set():
                    self._producer_error = str(error) or type(error).__name__
                    self._metrics["producer_error"] = self._producer_error
        finally:
            with self._condition:
                self._upstream_done = True
                self._metrics["upstream_end_monotonic"] = monotonic()
                self._condition.notify_all()
            self._close_result_once()

    def _write_buffered(self, data: bytes) -> None:
        offset = 0
        frame_bytes = self.audio_format.frame_bytes
        while offset < len(data):
            with self._condition:
                while (
                    self._buffer_bytes >= self.max_buffer_bytes
                    and not self._cancel_requested.is_set()
                    and not self._playback_error
                ):
                    self._metrics["producer_wait_count"] = int(
                        self._metrics["producer_wait_count"]
                    ) + 1
                    self._condition.wait(0.1)
                if self._cancel_requested.is_set():
                    raise _PlaybackCancelled
                if self._playback_error:
                    raise StreamingPlaybackError(self._playback_error)
                available = self.max_buffer_bytes - self._buffer_bytes
                take = min(len(data) - offset, available)
                take -= take % frame_bytes
                if take <= 0:
                    continue
                part = data[offset : offset + take]
                self._buffer.append(part)
                self._buffer_bytes += take
                offset += take
                self._metrics["buffer_peak_bytes"] = max(
                    int(self._metrics["buffer_peak_bytes"]), self._buffer_bytes
                )
                self._condition.notify_all()

    def _manager_main(self) -> None:
        output: RawPcmOutput | None = None
        try:
            with self._condition:
                while not self._cancel_requested.is_set() and not self._ready_to_start_locked():
                    self._condition.wait(0.1)
                if self._cancel_requested.is_set():
                    return
                if self._buffer_bytes == 0:
                    if not self._producer_error:
                        self._producer_error = "PCM stream completed without audio"
                        self._metrics["producer_error"] = self._producer_error
                    return

            output = self.output_factory.open(
                sample_rate=self.audio_format.sample_rate,
                channels=self.audio_format.channels,
                device=self.device,
                callback=self._audio_callback,
            )
            with self._condition:
                self._output = output
                if self._cancel_requested.is_set():
                    return
                self._metrics["playback_start_monotonic"] = monotonic()
                self._metrics["buffer_bytes_at_playback_start"] = self._buffer_bytes
            with self._output_control_lock:
                if self._cancel_requested.is_set():
                    return
                output.start()
                self._output_started = True
            while not output.wait(0.1):
                if self._cancel_requested.is_set() or self._playback_error:
                    with self._output_control_lock:
                        if self._output_started:
                            output.abort()
                            self._output_started = False
                            self._audio_stream_stopped.set()
                    break
            if self._cancel_requested.is_set() or self._playback_error:
                with self._output_control_lock:
                    if self._output_started:
                        output.abort()
                        self._output_started = False
                        self._audio_stream_stopped.set()
            with self._condition:
                self._metrics["playback_end_monotonic"] = monotonic()
                output_stopped_early = (
                    not self._cancel_requested.is_set()
                    and not self._playback_error
                    and not self._upstream_done
                )
                if output_stopped_early:
                    self._playback_error = "audio output stopped before PCM stream completed"
                    self._metrics["playback_error"] = self._playback_error
            if self._playback_error:
                self._cancel_requested.set()
                self._close_result_once()
        except Exception as error:
            with self._condition:
                self._playback_error = str(error) or type(error).__name__
                self._metrics["playback_error"] = self._playback_error
                self._condition.notify_all()
            self._cancel_requested.set()
            self._close_result_once()
            if output is not None:
                try:
                    with self._output_control_lock:
                        if self._output_started:
                            output.abort()
                            self._output_started = False
                            self._audio_stream_stopped.set()
                except Exception:
                    pass
        finally:
            if output is not None:
                try:
                    with self._output_control_lock:
                        output.close()
                        self._output_started = False
                except Exception as error:
                    with self._condition:
                        if not self._playback_error:
                            self._playback_error = str(error) or type(error).__name__
                            self._metrics["playback_error"] = self._playback_error
                finally:
                    self._audio_stream_stopped.set()
            else:
                self._audio_stream_stopped.set()
            if self._cancel_requested.is_set():
                self._close_result_once()
            if current_thread() is not self._producer_thread:
                self._producer_thread.join(self.close_timeout_seconds)
            if self._producer_thread.is_alive():
                with self._condition:
                    if not self._playback_error:
                        self._playback_error = "PCM producer thread did not exit"
                        self._metrics["playback_error"] = self._playback_error
            self._finish()

    def _ready_to_start_locked(self) -> bool:
        if self._buffer_bytes <= 0:
            return self._upstream_done
        if self._buffer_bytes >= self.prebuffer_bytes:
            return True
        return self._upstream_done

    def _audio_callback(self, outdata: memoryview, frames: int, status: object) -> bool:
        try:
            expected = int(frames) * self.audio_format.frame_bytes
            if expected <= 0 or outdata.nbytes != expected:
                raise StreamingPlaybackError("audio callback buffer size mismatch")
            outdata[:] = b"\0" * expected
            copied = 0
            with self._condition:
                if self._cancel_requested.is_set() or self._playback_error:
                    return False
                while copied < expected and self._buffer:
                    head = self._buffer[0]
                    available = len(head) - self._buffer_offset
                    take = min(expected - copied, available)
                    outdata[copied : copied + take] = head[
                        self._buffer_offset : self._buffer_offset + take
                    ]
                    copied += take
                    self._buffer_offset += take
                    self._buffer_bytes -= take
                    if self._buffer_offset == len(head):
                        self._buffer.popleft()
                        self._buffer_offset = 0
                if copied:
                    self._metrics["played_pcm_bytes"] = int(
                        self._metrics["played_pcm_bytes"]
                    ) + copied
                    if self._metrics["first_audio_submission_monotonic"] is None:
                        self._metrics["first_audio_submission_monotonic"] = monotonic()
                shortage = expected - copied
                device_underflow = bool(getattr(status, "output_underflow", False))
                if device_underflow:
                    self._metrics["device_underflow_count"] = int(
                        self._metrics["device_underflow_count"]
                    ) + 1
                if shortage and not self._upstream_done:
                    self._metrics["underrun_count"] = int(
                        self._metrics["underrun_count"]
                    ) + 1
                    self._metrics["underrun_frames"] = int(
                        self._metrics["underrun_frames"]
                    ) + shortage // self.audio_format.frame_bytes
                elif device_underflow:
                    self._metrics["underrun_count"] = int(
                        self._metrics["underrun_count"]
                    ) + 1
                if not self._upstream_done:
                    low = self._metrics["buffer_low_watermark"]
                    self._metrics["buffer_low_watermark"] = (
                        self._buffer_bytes
                        if low is None
                        else min(int(low), self._buffer_bytes)
                    )
                stop_after = self._upstream_done and self._buffer_bytes == 0
                self._condition.notify_all()
            return not stop_after
        except Exception as error:
            with self._condition:
                self._playback_error = str(error) or type(error).__name__
                self._metrics["playback_error"] = self._playback_error
                self._condition.notify_all()
            return False

    def _finish(self) -> None:
        with self._finalize_lock:
            if self._done.is_set():
                return
            with self._condition:
                if self._metrics["playback_end_monotonic"] is None:
                    self._metrics["playback_end_monotonic"] = monotonic()
                if self._metrics["buffer_low_watermark"] is None:
                    self._metrics["buffer_low_watermark"] = self._buffer_bytes
                self._complete_metrics_locked()
                if self._user_cancel_requested.is_set():
                    status = "cancelled"
                    reason = "cancelled"
                    warnings = [
                        message
                        for message in (self._producer_error, self._playback_error)
                        if message
                    ]
                elif self._producer_error or self._playback_error:
                    status = "failed"
                    reason = "streaming_playback_failed"
                    warnings = [
                        message
                        for message in (self._producer_error, self._playback_error)
                        if message
                    ]
                elif int(self._metrics["played_pcm_bytes"]) == 0:
                    status = "failed"
                    reason = "zero_audio"
                    warnings = ["PCM stream completed without playable audio"]
                else:
                    status = "completed"
                    reason = "completed"
                    underruns = int(self._metrics["underrun_count"])
                    warnings = (
                        [f"streaming playback inserted silence during {underruns} underrun callback(s)"]
                        if underruns
                        else []
                    )
                diagnostics = create_diagnostics(
                    stage="experience.audio.streaming_playback",
                    success=status == "completed",
                    reason=reason,
                    warnings=warnings,
                    metrics=deepcopy(self._metrics),
                )
            self._report = StreamingPlaybackReport(status=status, diagnostics=diagnostics)
            self._done.set()

    def _complete_metrics_locked(self) -> None:
        played = int(self._metrics["played_pcm_bytes"])
        self._metrics["audio_duration_ms"] = round(
            played * 1000.0 / self.audio_format.bytes_per_second, 3
        )
        request_start = float(self._metrics["request_start_monotonic"])
        playback_end = float(self._metrics["playback_end_monotonic"])
        self._metrics["wall_duration_ms"] = round(
            (playback_end - request_start) * 1000.0, 3
        )
        first_submission = self._metrics["first_audio_submission_monotonic"]
        self._metrics["request_to_first_audio_submission_ms"] = (
            round((float(first_submission) - request_start) * 1000.0, 3)
            if first_submission is not None
            else None
        )
        self._metrics["provider_closed"] = self.provider_closed
        self._metrics["audio_stream_stopped"] = self.audio_stream_stopped
        cancel_requested = self._metrics["cancel_requested_monotonic"]
        if cancel_requested is not None:
            cancel_completed = monotonic()
            self._metrics["cancel_completed_monotonic"] = cancel_completed
            self._metrics["cancel_latency_ms"] = round(
                (cancel_completed - float(cancel_requested)) * 1000.0, 3
            )

    def _close_result_once(self) -> None:
        with self._close_lock:
            if self._result_closed:
                return
            self._result_closed = True
        try:
            self.speech.cancel()
        except Exception as error:
            with self._condition:
                message = str(error) or type(error).__name__
                self._metrics["provider_close_error"] = message
                if not self._producer_error:
                    self._producer_error = message
                    self._metrics["producer_error"] = message
        finally:
            self._provider_close_finished.set()


class _PlaybackCancelled(Exception):
    pass


def _validate_metadata(metadata: Mapping[str, object]) -> _PcmFormat:
    if not isinstance(metadata, Mapping):
        raise StreamingPlaybackError("stream metadata must be a mapping")
    if str(metadata.get("sample_format", "")).lower() != "s16le":
        raise StreamingPlaybackError("streaming playback only supports s16le PCM")
    bits = metadata.get("bits_per_sample")
    if isinstance(bits, bool) or not isinstance(bits, int) or bits != 16:
        raise StreamingPlaybackError("streaming playback only supports 16-bit PCM")
    sample_rate = metadata.get("sample_rate")
    channels = metadata.get("channels")
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
        raise StreamingPlaybackError("sample_rate must be a positive integer")
    if isinstance(channels, bool) or not isinstance(channels, int) or channels <= 0:
        raise StreamingPlaybackError("channels must be a positive integer")
    if metadata.get("interleaved") is False:
        raise StreamingPlaybackError("non-interleaved PCM is not supported")
    return _PcmFormat(sample_rate=sample_rate, channels=channels)


def _milliseconds_to_bytes(milliseconds: float, bytes_per_second: int, frame_bytes: int) -> int:
    if milliseconds <= 0:
        return 0
    raw = ceil(bytes_per_second * milliseconds / 1000.0)
    return max(frame_bytes, ((raw + frame_bytes - 1) // frame_bytes) * frame_bytes)


def _wait_event_interruptibly(event: Event, timeout: float | None) -> bool:
    """Poll an Event so Windows regularly returns control to the main thread."""

    deadline = None if timeout is None else monotonic() + max(float(timeout), 0.0)
    while not event.is_set():
        wait_for = _INTERRUPTIBLE_WAIT_SLICE_SECONDS
        if deadline is not None:
            remaining = deadline - monotonic()
            if remaining <= 0:
                return event.is_set()
            wait_for = min(wait_for, remaining)
        event.wait(wait_for)
    return True


def _join_thread_interruptibly(thread: Thread, timeout: float) -> bool:
    """Join without one long Windows lock wait that delays KeyboardInterrupt."""

    deadline = monotonic() + max(float(timeout), 0.0)
    while thread.is_alive():
        remaining = deadline - monotonic()
        if remaining <= 0:
            return False
        thread.join(min(_INTERRUPTIBLE_WAIT_SLICE_SECONDS, remaining))
    return True
