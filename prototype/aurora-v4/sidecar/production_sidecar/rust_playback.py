"""Private file handoff adapter; never imports a Python audio device backend."""
import threading
import logging
import sys
from pathlib import Path

MAX_BYTES = 64 * 1024 * 1024


class RustPlayback:
    def __init__(self, root, send):
        self.root = Path(root).resolve() if root else None
        self.send = send
        self._lock = threading.RLock()
        self._subscribers = []
        self._identity = None
        self._speech = None
        self._playing = False
        self._submitted = False
        self._stop_sent = False
        self._stopped = threading.Event()
        self._stopped.set()
        self._last_state = None
        self._closed = False

    def bind(self, generation_id, revision):
        with self._lock:
            if not self._stopped.is_set() or self._closed:
                raise RuntimeError("AUDIO_OWNER_NOT_RELEASED")
            self._identity = dict(generation_id=generation_id, revision=revision)
            self._speech = None
            self._submitted = False
            self._stop_sent = False
            self._last_state = None

    def play(self, speech):
        with self._lock:
            if self._closed or not self._identity or self._submitted:
                raise RuntimeError("INVALID_AUDIO_OWNER")
            self._speech = speech
            if self.root is None or not speech.audio_path:
                raise RuntimeError("AUDIO_HANDOFF_UNAVAILABLE")
            path = Path(speech.audio_path).resolve(strict=True)
            relative = path.relative_to(self.root).as_posix()
            if path.stat().st_size > MAX_BYTES:
                raise RuntimeError("AUDIO_SIZE_LIMIT")
            self._submitted = True
            self._stopped.clear()
            logging.getLogger("aurora-v4-audio").info("event=audio_handoff backend=rust python_audio_loaded=%s", "pygame" in sys.modules)
            if not self.send("audio.play.request", {**self._identity, "file": relative}):
                self.disconnected()

    def accept(self, payload):
        from modules.experience.audio.playback import PlaybackEvent, PlaybackEventType
        with self._lock:
            identity = {k: payload[k] for k in ("generation_id", "revision")}
            if identity != self._identity or self._stopped.is_set():
                return
            state = payload["state"]
            if state == self._last_state:
                return
            self._last_state = state
            self._playing = state == "started"
            if state != "started":
                self._stopped.set()  # fact after Rust released device/decoder
            types = {"started": PlaybackEventType.STARTED, "completed": PlaybackEventType.COMPLETED,
                     "stopped": PlaybackEventType.STOPPED, "failed": PlaybackEventType.FAILED}
            event = PlaybackEvent(types[state], speech=self._speech, error=payload["error_code"])
            callbacks = tuple(self._subscribers)
        # Never call Voice while holding adapter lock (Voice -> adapter also exists).
        for callback in callbacks:
            callback(event)

    def stop(self):
        with self._lock:
            if self._submitted and not self._stopped.is_set() and not self._stop_sent:
                self._stop_sent = True
                if not self.send("audio.stop.request", self._identity.copy()):
                    self.disconnected()

    def disconnected(self):
        # Desktop transport loss owns audio stop. No fresh playback is possible.
        with self._lock:
            notify = self._submitted and not self._stopped.is_set()
            callbacks = tuple(self._subscribers) if notify else ()
            speech = self._speech
            self._closed = True
            self._playing = False
            self._stopped.set()
        if callbacks:
            from modules.experience.audio.playback import PlaybackEvent, PlaybackEventType
            for callback in callbacks:
                callback(PlaybackEvent(PlaybackEventType.FAILED, speech=speech, error="AUDIO_TRANSPORT_LOST"))

    def wait_stopped(self):
        if not self._stopped.wait(5):
            # No implicit fallback, and no subsequent owner after missing ACK.
            self.disconnected()
            raise RuntimeError("AUDIO_ACK_TIMEOUT")

    def is_playing(self):
        with self._lock:
            return self._playing

    def subscribe(self, callback):
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)
        return callback

    def unsubscribe(self, callback):
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)
                return True
        return False

    def unload(self):
        pass  # Rust owns all open audio handles

    def shutdown(self):
        self.stop()
        self.wait_stopped()
        self.disconnected()
