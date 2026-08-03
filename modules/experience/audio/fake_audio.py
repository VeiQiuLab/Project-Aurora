"""Deterministic audio runtime implementations for tests."""

from __future__ import annotations

from threading import RLock

from modules.experience.voice.models import AudioInput, SpeechResult

from .playback import (
    AudioPlaybackController,
    PlaybackCallback,
    PlaybackEvent,
    PlaybackEventType,
)
from .recorder import AudioRecorder


class FakeRecorder(AudioRecorder):
    """Return fixed audio without accessing a microphone."""

    def __init__(
        self,
        audio_input: AudioInput | None = None,
        *,
        start_error: Exception | None = None,
        stop_error: Exception | None = None,
        cancel_error: Exception | None = None,
    ):
        self.audio_input = audio_input or AudioInput(kind="bytes", data=b"fake-input")
        self.start_error = start_error
        self.stop_error = stop_error
        self.cancel_error = cancel_error
        self.start_calls = 0
        self.stop_calls = 0
        self.cancel_calls = 0
        self._recording = False
        self._lock = RLock()

    def start(self) -> None:
        with self._lock:
            if self.start_error is not None:
                raise self.start_error
            if self._recording:
                raise RuntimeError("recording is already active")
            self._recording = True
            self.start_calls += 1

    def stop(self) -> AudioInput:
        with self._lock:
            if self.stop_error is not None:
                raise self.stop_error
            if not self._recording:
                raise RuntimeError("recording is not active")
            self._recording = False
            self.stop_calls += 1
            return self.audio_input

    def cancel(self) -> None:
        with self._lock:
            if self.cancel_error is not None:
                raise self.cancel_error
            self._recording = False
            self.cancel_calls += 1


class FakePlayback(AudioPlaybackController):
    """Record playback requests without accessing a speaker."""

    def __init__(
        self,
        *,
        play_error: Exception | None = None,
        stop_error: Exception | None = None,
        auto_complete: bool = False,
    ):
        self.play_error = play_error
        self.stop_error = stop_error
        self.auto_complete = auto_complete
        self.played: list[SpeechResult] = []
        self.stop_calls = 0
        self._playing = False
        self._subscribers: list[PlaybackCallback] = []
        self._lock = RLock()

    def play(self, speech: SpeechResult) -> None:
        event = None
        with self._lock:
            if not isinstance(speech, SpeechResult):
                raise TypeError("speech must be a SpeechResult")
            if self.play_error is not None:
                event = PlaybackEvent(
                    event_type=PlaybackEventType.FAILED,
                    speech=speech,
                    error=str(self.play_error),
                )
            else:
                self.played.append(speech)
                self._playing = True
                event = PlaybackEvent(
                    event_type=PlaybackEventType.STARTED,
                    speech=speech,
                )
        self._emit(event)
        if self.play_error is not None:
            raise self.play_error
        if self.auto_complete:
            self.complete()

    def stop(self) -> None:
        event = None
        with self._lock:
            if self.stop_error is not None:
                event = PlaybackEvent(
                    event_type=PlaybackEventType.FAILED,
                    error=str(self.stop_error),
                )
            else:
                was_playing = self._playing
                self._playing = False
                self.stop_calls += 1
                if was_playing:
                    event = PlaybackEvent(event_type=PlaybackEventType.STOPPED)
        if event is not None:
            self._emit(event)
        if self.stop_error is not None:
            raise self.stop_error

    def is_playing(self) -> bool:
        with self._lock:
            return self._playing

    def complete(self) -> None:
        """Finish fake playback and emit the completion event."""

        with self._lock:
            if not self._playing:
                return
            self._playing = False
        self._emit(PlaybackEvent(event_type=PlaybackEventType.COMPLETED))

    def subscribe(self, callback: PlaybackCallback) -> PlaybackCallback:
        if not callable(callback):
            raise TypeError("callback must be callable")
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)
        return callback

    def unsubscribe(self, callback: PlaybackCallback) -> bool:
        with self._lock:
            if callback not in self._subscribers:
                return False
            self._subscribers.remove(callback)
            return True

    def _emit(self, event: PlaybackEvent) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers)
        for callback in subscribers:
            try:
                callback(event)
            except Exception:
                continue
