import io
import json
import socket
from threading import Event
from urllib.error import HTTPError, URLError

import pytest

from aurora_voice_node.stream_protocol import CONTENT_TYPE, encode_frame, encode_json_frame, metadata_payload
from modules.experience.voice.models import VoiceOptions
from modules.experience.voice.providers.remote_cosyvoice import (
    RemoteCosyVoiceProvider,
    StreamingSynthesisError,
)
from wav_helpers import make_wav


class FakeResponse:
    def __init__(self, body: bytes, *, status: int = 200, content_type: str = "audio/wav"):
        self.body = body
        self.status = status
        self.headers = {"Content-Type": content_type}
        self.offset = 0
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit=-1):
        if limit < 0:
            data = self.body[self.offset :]
            self.offset = len(self.body)
            return data
        data = self.body[self.offset : self.offset + limit]
        self.offset += len(data)
        return data

    read1 = read

    def close(self):
        self.closed = True


def test_provider_returns_valid_wav_for_existing_playback(tmp_path):
    calls = []
    wav = make_wav()

    def open_request(request, *, timeout):
        calls.append((request, timeout))
        return FakeResponse(wav)

    provider = RemoteCosyVoiceProvider(
        "http://voice-node.test:8765/",
        output_dir=tmp_path,
        http_open=open_request,
    )
    result = provider.synthesize("你好", VoiceOptions(rate=1.25), timeout_seconds=8)

    assert result.audio_bytes == wav
    assert result.audio_path is not None
    assert result.mime_type == "audio/wav"
    assert result.duration_ms == 10
    assert result.diagnostics["success"] is True
    request, timeout = calls[0]
    assert request.full_url == "http://voice-node.test:8765/tts"
    assert json.loads(request.data.decode("utf-8")) == {"text": "你好", "speed": 1.25}
    assert timeout == 8


def test_provider_rejects_empty_text_without_network_call():
    provider = RemoteCosyVoiceProvider(
        "http://voice-node.test",
        http_open=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network called")),
    )

    result = provider.synthesize("   ")

    assert result.audio_path is None
    assert result.diagnostics["reason"] == "empty_text"


def test_provider_reports_offline_node():
    def offline(*_args, **_kwargs):
        raise URLError(ConnectionRefusedError())

    result = RemoteCosyVoiceProvider("http://voice-node.test", http_open=offline).synthesize("hello")

    assert result.diagnostics["reason"] == "connection_failed"


def test_provider_reports_timeout():
    def timeout(*_args, **_kwargs):
        raise socket.timeout()

    result = RemoteCosyVoiceProvider("http://voice-node.test", http_open=timeout).synthesize("hello")

    assert result.diagnostics["reason"] == "timeout"


def test_provider_reports_server_error_payload():
    payload = json.dumps({"error": {"message": "runtime unavailable"}}).encode()

    def failed(request, **_kwargs):
        raise HTTPError(request.full_url, 503, "unavailable", {}, io.BytesIO(payload))

    result = RemoteCosyVoiceProvider("http://voice-node.test", http_open=failed).synthesize("hello")

    assert result.diagnostics["reason"] == "server_error"
    assert result.diagnostics["metrics"]["status"] == 503
    assert "runtime unavailable" in result.diagnostics["trace"]["message"]


def test_provider_rejects_non_wav_response():
    provider = RemoteCosyVoiceProvider(
        "http://voice-node.test",
        http_open=lambda *_args, **_kwargs: FakeResponse(b"{}", content_type="application/json"),
    )

    result = provider.synthesize("hello")

    assert result.diagnostics["reason"] == "invalid_response"


def test_provider_rejects_invalid_wav():
    provider = RemoteCosyVoiceProvider(
        "http://voice-node.test",
        http_open=lambda *_args, **_kwargs: FakeResponse(b"RIFF" + b"\0" * 64),
    )

    result = provider.synthesize("hello")

    assert result.diagnostics["reason"] == "invalid_wav"


def test_health_requires_runtime_readiness():
    payload = json.dumps({"status": "degraded", "runtime": {"available": False}}).encode()
    provider = RemoteCosyVoiceProvider(
        "http://voice-node.test",
        http_open=lambda *_args, **_kwargs: FakeResponse(payload, content_type="application/json"),
    )

    available, detail = provider.health()

    assert available is False
    assert "runtime is unavailable" in detail


def framed_stream(*, terminal="E"):
    audio = [b"\1\0" * 10, b"\2\0" * 5]
    body = encode_json_frame("M", metadata_payload(sample_rate=24000))
    body += b"".join(encode_frame("A", chunk) for chunk in audio)
    if terminal == "E":
        body += encode_json_frame("E", {"total_samples": 15, "audio_frames": 2})
    elif terminal == "X":
        body += encode_json_frame("X", {"code": "upstream_failed", "message": "generation failed"})
    return body


def test_streaming_provider_returns_metadata_and_pcm_iterator():
    calls = []

    def open_request(request, *, timeout):
        calls.append((request, timeout))
        return FakeResponse(framed_stream(), content_type=CONTENT_TYPE)

    provider = RemoteCosyVoiceProvider("http://voice-node.test", http_open=open_request)
    result = provider.synthesize_stream("你好", VoiceOptions(rate=1.2), timeout_seconds=8)
    chunks = list(result.chunks)

    assert result.metadata["sample_format"] == "s16le"
    assert result.metadata["sample_rate"] == 24000
    assert chunks == [b"\1\0" * 10, b"\2\0" * 5]
    assert result.diagnostics["success"] is True
    assert result.diagnostics["reason"] == "stream_completed"
    assert result.diagnostics["metrics"]["total_samples"] == 15
    request, timeout = calls[0]
    assert request.full_url == "http://voice-node.test/tts/stream"
    assert json.loads(request.data.decode("utf-8")) == {"text": "你好", "speed": 1.2}
    assert timeout == 8


def test_streaming_error_frame_raises_and_never_completes_successfully():
    provider = RemoteCosyVoiceProvider(
        "http://voice-node.test",
        http_open=lambda *_args, **_kwargs: FakeResponse(framed_stream(terminal="X"), content_type=CONTENT_TYPE),
    )
    result = provider.synthesize_stream("hello")

    with pytest.raises(StreamingSynthesisError, match="generation failed"):
        list(result.chunks)

    assert result.diagnostics["success"] is False
    assert result.diagnostics["reason"] == "upstream_failed"


def test_eof_without_end_is_a_streaming_failure():
    provider = RemoteCosyVoiceProvider(
        "http://voice-node.test",
        http_open=lambda *_args, **_kwargs: FakeResponse(framed_stream(terminal=None), content_type=CONTENT_TYPE),
    )
    result = provider.synthesize_stream("hello")

    with pytest.raises(StreamingSynthesisError, match="without E or X"):
        list(result.chunks)

    assert result.diagnostics["reason"] == "invalid_stream"


def test_stream_close_and_cancel_close_network_response():
    response = FakeResponse(framed_stream(), content_type=CONTENT_TYPE)
    provider = RemoteCosyVoiceProvider(
        "http://voice-node.test", http_open=lambda *_args, **_kwargs: response
    )
    result = provider.synthesize_stream("hello")
    result.cancel()

    assert response.closed is True
    assert result.diagnostics["reason"] == "cancelled"


def test_stream_rejects_pre_cancelled_request_without_network():
    cancelled = Event()
    cancelled.set()
    provider = RemoteCosyVoiceProvider(
        "http://voice-node.test",
        http_open=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network called")),
    )

    result = provider.synthesize_stream("hello", cancel_event=cancelled)

    assert result.metadata == {}
    assert result.diagnostics["reason"] == "cancelled"
