"""Client of the Desktop-owned private voice broker. Never owns processes."""
from __future__ import annotations

import http.client
import io
import json
import os
import threading
import wave
from time import monotonic
from urllib.parse import urlsplit

from modules.diagnostics import create_diagnostics
from ..interfaces import TTSProvider
from ..models import SpeechResult, TTSRequest, VoiceOptions


class LocalSherpaMeloProvider(TTSProvider):
    def __init__(self, endpoint=None, token=None):
        self._endpoint = endpoint if endpoint is not None else os.environ.get("AURORA_LOCAL_VOICE_ENDPOINT", "")
        self._token = token if token is not None else os.environ.get("AURORA_LOCAL_VOICE_TOKEN", "")
        self._generation = ""
        self._revision = 0

    def bind(self, generation_id, preparing_revision):
        self._generation, self._revision = generation_id, preparing_revision

    def _connection(self, timeout):
        parsed = urlsplit(self._endpoint)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port or
                parsed.path not in {"", "/"} or parsed.username or parsed.password or parsed.query or parsed.fragment or
                len(self._token) != 64):
            raise ValueError("PRIVATE_VOICE_UNAVAILABLE")
        return http.client.HTTPConnection("127.0.0.1", parsed.port, timeout=timeout)

    def _request(self, path, payload, timeout):
        connection = self._connection(timeout)
        try:
            connection.request("POST", path, json.dumps(payload),
                {"Authorization": "Bearer " + self._token, "Content-Type": "application/json"})
            response = connection.getresponse()
            content = response.read(64 * 1024 * 1024 + 1)
            if len(content) > 64 * 1024 * 1024:
                raise ValueError("INVALID_ARTIFACT")
            return response.status, content
        finally:
            connection.close()

    def synthesize(self, text, options=None, *, timeout_seconds=None, cancel_event=None):
        return self.synthesize_request(TTSRequest(text, options or VoiceOptions(), timeout_seconds, cancel_event))

    def synthesize_request(self, request):
        started = monotonic()
        timeout = request.timeout_seconds if request.timeout_seconds is not None else 30.
        result = []
        identity = dict(generation_id=self._generation, revision=self._revision)
        payload = dict(identity, text=request.text, timeout_seconds=timeout,
                       speaker="melo-fixed-0", speed=request.options.rate)
        reason = "synthesis_failed"
        if (not isinstance(request.text, str) or not request.text.strip() or
                len(request.text.encode("utf-8")) > 8000 or not self._generation or
                not 0 < timeout <= 120):
            return self._failure("invalid_request", started)
        if request.cancel_event and request.cancel_event.is_set():
            return self._failure("cancelled", started)
        # The transport worker has a bounded socket deadline. Logical Stop does
        # not wait for a non-interruptible native ONNX call or its HTTP response.
        def send():
            try:
                result.append(self._request("/synthesize", payload, timeout + 1))
            except (OSError, ValueError, http.client.HTTPException):
                result.append((503, b""))
        worker = threading.Thread(target=send, name="aurora-local-voice-request", daemon=True)
        worker.start()
        deadline = started + timeout
        while worker.is_alive():
            if (request.cancel_event and request.cancel_event.is_set()) or monotonic() >= deadline:
                reason = "cancelled" if request.cancel_event and request.cancel_event.is_set() else "timeout"
                try:
                    self._request("/cancel", identity, .3)
                except (OSError, ValueError, http.client.HTTPException):
                    pass
                return self._failure(reason, started)
            worker.join(.02)
        if request.cancel_event and request.cancel_event.is_set():
            return self._failure("cancelled", started)
        status, data = result[0]
        if status != 200:
            reason = "connection_failed" if status == 503 else "timeout" if status == 408 else "synthesis_failed"
            return self._failure(reason, started)
        try:
            with wave.open(io.BytesIO(data), "rb") as audio:
                if (audio.getnchannels() != 1 or audio.getsampwidth() != 2 or
                        audio.getframerate() != 44100 or audio.getnframes() <= 0 or
                        len(audio.readframes(audio.getnframes())) != audio.getnframes() * 2):
                    raise ValueError()
                duration = round(audio.getnframes() / 44100 * 1000)
        except (ValueError, EOFError, wave.Error):
            return self._failure("invalid_artifact", started)
        return SpeechResult(audio_bytes=data, duration_ms=duration, diagnostics=create_diagnostics(
            stage="experience.voice.tts.local_sherpa_melo", success=True, reason="completed",
            metrics={"provider": "local_sherpa_melo", "synthesis_ms": (monotonic()-started)*1000,
                     "speaker": "melo-fixed-0", "num_threads": 4}))

    @staticmethod
    def _failure(reason, started):
        return SpeechResult(diagnostics=create_diagnostics(stage="experience.voice.tts.local_sherpa_melo",
            success=False, reason=reason, metrics={"provider": "local_sherpa_melo",
                "synthesis_ms": (monotonic()-started)*1000}))
