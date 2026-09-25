"""Completed-turn TTS integration; Python owns routing and Voice cancellation.

No chat generation, microphone, PCM IPC or streaming playback is created here.
The existing Chat generation ID is the only turn owner. A serial execution lock
keeps old audio cleanup from touching a newer turn's mixer resources.
"""
from __future__ import annotations

import logging
import tempfile
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from time import monotonic

LOGGER = logging.getLogger("aurora-v4-voice")
PROVIDERS = {"edge_tts", "remote_cosyvoice", "fake"}


@dataclass(eq=False)
class VoiceRun:
    generation_id: str
    settings: object
    text: str = field(repr=False)
    cancel: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)
    playback_done: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    speech: object = None
    error: str = ""
    revision: int = 0


def create_router(settings, output_dir):
    # Reuse production selection/registration, without constructing STT/VAD or
    # a second VoiceOrchestrator/LLM. All generated files are request-owned.
    from modules.experience.voice.integration import _create_tts
    router = _create_tts(settings)
    provider = router.provider_for()
    if hasattr(provider, "output_dir"):
        provider.output_dir = Path(output_dir)
    return router


def create_playback():
    # Production must inject the private Rust bridge, never silently use pygame.
    raise RuntimeError("RUST_AUDIO_BRIDGE_REQUIRED")


class VoiceExecution:
    def __init__(self, settings, notify, *, router_factory=create_router,
                 playback_factory=create_playback, audio_root=None):
        self.settings = settings
        self.notify = notify
        self.router_factory = router_factory
        self.playback_factory = playback_factory
        self.audio_root = audio_root
        self._lock = threading.RLock()
        self._serial = threading.Lock()
        self._workers = set()
        self._active = None
        self._playback = None
        self._connection = None
        self._generation = None
        self._claimed = False
        self._closed = False
        self._revision = 0
        self._state = "idle"
        self._error = ""

    def _snapshot_locked(self):
        snapshot = self.settings.snapshot()
        selected = snapshot.get("voice.tts.provider", "edge_tts")
        return dict(revision=self._revision, state=self._state,
                    enabled=(snapshot.get("voice.enabled", False) is True and
                             snapshot.get("voice.playback.enabled", True) is True),
                    provider=selected if selected in PROVIDERS else "",
                    generation_id=self._generation, error_code=self._error)

    def snapshot(self):
        with self._lock:
            return self._snapshot_locked()

    def _publish(self, state, error=""):
        # Called under RLock, including from synchronous playback callbacks.
        self._state, self._error = state, error
        self._revision += 1
        snapshot = self._snapshot_locked()
        LOGGER.info("event=voice_state state=%s revision=%s error_code=%s", state,
                    self._revision, error)
        try:
            self.notify(snapshot)
        except Exception:
            # Transport visibility must never change Chat or Voice ownership.
            LOGGER.warning("event=voice_notification_failed")

    def _cancel_locked(self):
        run = self._active
        if run is not None and not run.finished.is_set():
            run.cancel.set()  # truth before playback/network side effects
            run.playback_done.set()
            self._publish("stopping")
            if self._playback is not None:
                try:
                    self._playback.stop()
                except Exception:
                    LOGGER.warning("event=voice_stop_failed")

    def begin(self, generation_id, connection):
        self.reap()
        with self._lock:
            if self._closed:
                return
            self._cancel_locked()
            self._generation, self._connection = generation_id, connection
            self._claimed = False
            self._publish("idle")

    def stop(self, target_generation_id=None, *, connection=None):
        with self._lock:
            if connection is not None and connection is not self._connection:
                return self._snapshot_locked()
            if target_generation_id is not None and target_generation_id != self._generation:
                return self._snapshot_locked()
            self._claimed = True  # also suppress not-yet-scheduled final TTS
            self._cancel_locked()
            if self._active is None or self._active.finished.is_set():
                self._publish("idle")
            return self._snapshot_locked()

    def settings_changed(self):
        # A settings edit never hot-swaps a provider beneath an active request.
        # Cancel existing speech and use the authoritative snapshot next turn.
        with self._lock:
            self.stop()

    def completed(self, generation_id, text):
        self.reap()
        with self._lock:
            if self._closed or self._generation != generation_id or self._claimed:
                return False
            self._claimed = True
            snapshot = self.settings.snapshot()
            if (snapshot.get("voice.enabled", False) is not True or
                    snapshot.get("voice.playback.enabled", True) is not True or
                    not isinstance(text, str) or not text.strip()):
                return False
            run = VoiceRun(generation_id, snapshot, text.strip())
            self._active = run
            self._publish("preparing")
            run.revision = self._revision
            run.thread = threading.Thread(target=self._execute, args=(run,),
                                          name="aurora-v4-voice", daemon=False)
            self._workers.add(run)
            try:
                run.thread.start()
            except Exception:
                self._workers.discard(run)
                self._active = None
                run.finished.set()
                self._publish("error", "VOICE_UNAVAILABLE")
                return False
            return True

    def _owns(self, run):
        return (not self._closed and self._active is run and
                self._generation == run.generation_id and not run.cancel.is_set())

    def _execute(self, run):
        try:
            # Cancellation while queued never calls a provider. Cleanup of N
            # completes before N+1 touches the shared legacy playback object.
            while not self._serial.acquire(timeout=.02):
                if run.cancel.is_set():
                    return
            try:
                if run.cancel.is_set():
                    return
                self._speak(run)
            finally:
                self._serial.release()
        except Exception:
            # Raw provider errors may contain URLs, paths or input text.
            run.error = run.error or "SYNTHESIS_FAILED"
        finally:
            with self._lock:
                run.finished.set()
                if self._active is run:
                    self._active = None
                    if self._generation == run.generation_id and not self._closed:
                        if run.cancel.is_set():
                            self._publish("idle")
                        elif run.error:
                            self._publish("error", run.error)
                        else:
                            self._publish("idle")
                # Reap finished handles on the next operation/close, after the
                # actual thread returns (not merely when this finally runs).

    def _speak(self, run):
        from modules.experience.voice.models import VoiceOptions
        from modules.experience.audio.playback import PlaybackEventType

        def callback(event):
            with self._lock:
                if not self._owns(run) or event.speech is not run.speech:
                    return
                if event.event_type == PlaybackEventType.STARTED:
                    self._publish("speaking")
                elif event.event_type == PlaybackEventType.FAILED:
                    run.error = "PLAYBACK_FAILED"
                    run.playback_done.set()
                elif event.event_type in {PlaybackEventType.COMPLETED, PlaybackEventType.STOPPED}:
                    run.playback_done.set()

        with tempfile.TemporaryDirectory(prefix="aurora-v4-voice-", dir=self.audio_root) as output:
            try:
                router = self.router_factory(run.settings, output)
                timeout = float(run.settings.get("voice.tts.timeout_seconds", 30.0))
                if not 0 < timeout <= 120:
                    raise ValueError()
            except Exception:
                run.error = "INVALID_VOICE_SETTINGS"
                return
            if run.cancel.is_set():
                return
            speech = router.synthesize(run.text,
                VoiceOptions(voice=run.settings.get("voice.tts.voice", "")),
                timeout_seconds=timeout, cancel_event=run.cancel)
            if self.audio_root and not speech.audio_path and speech.audio_bytes and not run.cancel.is_set():
                if len(speech.audio_bytes) > 64 * 1024 * 1024:
                    run.error = "PLAYBACK_FAILED"
                    return
                suffix = ".mp3" if speech.mime_type == "audio/mpeg" else ".wav"
                path = Path(output) / ("speech" + suffix)
                path.write_bytes(speech.audio_bytes)
                speech = replace(speech, audio_path=str(path), audio_bytes=None)
            with self._lock:
                if not self._owns(run):
                    return
                if speech.diagnostics.get("success") is False or not (speech.audio_path or speech.audio_bytes):
                    reason = speech.diagnostics.get("reason", "")
                    run.error = ("VOICE_TIMEOUT" if reason == "timeout" else
                                 "VOICE_UNAVAILABLE" if reason in {"connection_failed", "dependency_missing"} else
                                 "SYNTHESIS_FAILED")
                    return
                run.speech = speech
                if self._playback is None:
                    try:
                        self._playback = self.playback_factory()
                    except Exception:
                        run.error = "PLAYBACK_FAILED"
                        return
                playback = self._playback
                playback.subscribe(callback)
                try:
                    bind = getattr(playback, "bind", None)
                    if callable(bind):
                        bind(run.generation_id, run.revision)
                    playback.play(speech)
                except Exception:
                    run.error = "PLAYBACK_FAILED"
                    run.playback_done.set()
            try:
                deadline = monotonic() + max(1, min(600, float(run.settings.get("voice.playback.timeout_seconds", 120))))
                while not run.playback_done.wait(.02):
                    if run.cancel.is_set():
                        break
                    if monotonic() >= deadline:
                        run.error = "VOICE_TIMEOUT"
                        break
            finally:
                with self._lock:
                    # Serial lock guarantees no newer run can be using mixer.
                    playback.unsubscribe(callback)
                    playback.stop()
                    unload = getattr(playback, "unload", None)
                    if callable(unload):
                        unload()
                wait_stopped = getattr(playback, "wait_stopped", None)
                if callable(wait_stopped):
                    wait_stopped()

    def reap(self):
        with self._lock:
            finished = [r for r in self._workers if r.thread and not r.thread.is_alive()]
            for run in finished:
                run.thread.join()
                self._workers.discard(run)

    def close(self):
        with self._lock:
            self._closed = True
            self._claimed = True
            self._cancel_locked()
            workers = tuple(self._workers)
            for run in workers:
                run.cancel.set()
                run.playback_done.set()
        # Never join under state lock; callbacks/worker finally need that lock.
        for run in workers:
            if run.thread is not threading.current_thread():
                run.thread.join()
        with self._lock:
            self._workers.clear()
            playback, self._playback = self._playback, None
            self._active = None
            self._state = "idle"
        if playback is not None:
            playback.shutdown()
