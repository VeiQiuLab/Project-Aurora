"""Optional pygame-backed MP3 playback controller."""

from __future__ import annotations

import time
from pathlib import Path
from threading import RLock, Thread
from typing import Any

from modules.diagnostics import create_diagnostics
from modules.experience.voice.models import SpeechResult

from .playback import (
    AudioPlaybackController,
    PlaybackCallback,
    PlaybackEvent,
    PlaybackEventType,
)


class RealPlaybackController(AudioPlaybackController):
    """Play file-backed audio through the optional pygame mixer."""

    def __init__(self, *, mixer: Any | None = None, poll_interval: float = 0.05):
        self._mixer = mixer
        self._mixer_error: Exception | None = None
        self._poll_interval = max(float(poll_interval), 0.01)
        self._subscribers: list[PlaybackCallback] = []
        self._lock = RLock()
        self._playing = False
        self._playback_token = 0

    @property
    def dependency_error(self) -> Exception | None:
        return self._mixer_error

    def play(self, speech: SpeechResult) -> None:
        if not isinstance(speech, SpeechResult):
            self._emit_failure("speech must be a SpeechResult")
            return
        if not speech.audio_path:
            self._emit_failure("RealPlaybackController requires SpeechResult.audio_path")
            return
        audio_path = Path(speech.audio_path)
        if not audio_path.is_file():
            self._emit_failure(f"audio file does not exist: {audio_path}", speech)
            return

        mixer = self._get_mixer()
        if mixer is None:
            self._emit_failure(
                "pygame is unavailable or the audio device could not be initialized",
                speech,
            )
            return

        try:
            with self._lock:
                if self._playing:
                    mixer.music.stop()
                    self._unload_music(mixer)
                    self._playing = False
                    self._playback_token += 1
                    stopped_event = PlaybackEvent(
                        event_type=PlaybackEventType.STOPPED,
                        speech=speech,
                        diagnostics=self._diagnostics("replaced"),
                    )
                else:
                    stopped_event = None
                mixer.music.load(str(audio_path))
                mixer.music.play()
                self._playing = True
                self._playback_token += 1
                token = self._playback_token
            if stopped_event is not None:
                self._emit(stopped_event)
            self._emit(
                PlaybackEvent(
                    event_type=PlaybackEventType.STARTED,
                    speech=speech,
                    diagnostics=self._diagnostics("started"),
                )
            )
            Thread(target=self._monitor_playback, args=(token, speech), daemon=True).start()
        except Exception as error:
            with self._lock:
                self._playing = False
                self._playback_token += 1
            self._emit_failure(str(error), speech, warning=type(error).__name__)

    def stop(self) -> None:
        with self._lock:
            if not self._playing:
                return
            mixer = self._mixer
            self._playing = False
            self._playback_token += 1
        try:
            mixer.music.stop()
            self._unload_music(mixer)
        except Exception as error:
            self._emit_failure(str(error), warning=type(error).__name__)
            return
        self._emit(
            PlaybackEvent(
                event_type=PlaybackEventType.STOPPED,
                diagnostics=self._diagnostics("stopped"),
            )
        )

    def is_playing(self) -> bool:
        with self._lock:
            return self._playing

    def unload(self) -> None:
        """Release the currently loaded audio resource without changing global state."""

        with self._lock:
            mixer = self._mixer
        if mixer is not None:
            self._unload_music(mixer)

    def shutdown(self) -> None:
        """Stop playback and release the pygame mixer for application shutdown."""

        self.stop()
        self.unload()
        with self._lock:
            mixer = self._mixer
        if mixer is not None:
            try:
                mixer.quit()
            except AttributeError:
                return
            except Exception:
                return

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

    def _get_mixer(self) -> Any | None:
        with self._lock:
            if self._mixer is not None:
                return self._mixer
            if self._mixer_error is not None:
                return None
            try:
                import pygame

                pygame.mixer.init()
                self._mixer = pygame.mixer
            except Exception as error:
                self._mixer_error = error
            return self._mixer

    def _monitor_playback(self, token: int, speech: SpeechResult) -> None:
        while True:
            time.sleep(self._poll_interval)
            with self._lock:
                if token != self._playback_token or not self._playing:
                    return
                mixer = self._mixer
            try:
                is_busy = bool(mixer.music.get_busy())
            except Exception as error:
                with self._lock:
                    if token == self._playback_token:
                        self._playing = False
                        self._playback_token += 1
                self._emit_failure(str(error), speech, warning=type(error).__name__)
                return
            if not is_busy:
                with self._lock:
                    if token != self._playback_token or not self._playing:
                        return
                    self._playing = False
                self._unload_music(mixer)
                self._emit(
                    PlaybackEvent(
                        event_type=PlaybackEventType.COMPLETED,
                        speech=speech,
                        diagnostics=self._diagnostics("completed"),
                    )
                )
                return

    def _emit_failure(
        self,
        message: str,
        speech: SpeechResult | None = None,
        *,
        warning: str | None = None,
    ) -> None:
        self._emit(
            PlaybackEvent(
                event_type=PlaybackEventType.FAILED,
                speech=speech,
                error=message,
                diagnostics=create_diagnostics(
                    stage="experience.audio.playback",
                    success=False,
                    reason="playback_failed",
                    warnings=[warning] if warning else [message],
                    trace={"message": message},
                ),
            )
        )

    @staticmethod
    def _unload_music(mixer: Any) -> None:
        try:
            unload = getattr(mixer.music, "unload", None)
            if callable(unload):
                unload()
        except Exception:
            return

    @staticmethod
    def _diagnostics(reason: str):
        return create_diagnostics(
            stage="experience.audio.playback",
            success=True,
            reason=reason,
            metrics={"backend": "pygame.mixer"},
        )

    def _emit(self, event: PlaybackEvent) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers)
        for callback in subscribers:
            try:
                callback(event)
            except Exception:
                continue
