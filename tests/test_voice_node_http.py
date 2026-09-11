import http.client
import json
import struct
from threading import Event, Thread
from time import sleep
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from aurora_voice_node.runtime import RuntimeTimedOut, RuntimeUnavailable
from aurora_voice_node.server import create_server
from aurora_voice_node.stream_protocol import CONTENT_TYPE, StreamFrameDecoder
from aurora_voice_node.wav_utils import WAVE_FORMAT_IEEE_FLOAT, inspect_wav
from modules.experience.voice.models import VoiceOptions
from modules.experience.voice.providers.remote_cosyvoice import RemoteCosyVoiceProvider
from wav_helpers import make_wav


class FakePcmStream:
    def __init__(self, chunks, *, error=None, closed=None):
        self.chunks = chunks
        self.error = error
        self.closed = closed or Event()

    def __iter__(self):
        yield from self.chunks
        if self.error is not None:
            raise self.error

    def close(self):
        self.closed.set()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class FakeRuntime:
    def __init__(self, *, audio=None, error=None, available=True, stream_chunks=None, stream_error=None):
        self.audio = audio if audio is not None else make_wav()
        self.error = error
        self.available = available
        self.calls = []
        self.stream_chunks = stream_chunks if stream_chunks is not None else [b"\0\0" * 3000]
        self.stream_error = stream_error
        self.stream_calls = []
        self.stream_closed = Event()

    def health(self):
        return {
            "backend": "server",
            "available": self.available,
            "state": "ready" if self.available else "failed",
            "process_running": self.available,
            "pid": 4321 if self.available else None,
            "restart_count": 0,
            "streaming": True,
            "sample_rate": 24000,
            "channels": 1,
            "last_error": "" if self.available else "test failure",
        }

    def synthesize(self, text, speed):
        self.calls.append((text, speed))
        if self.error is not None:
            raise self.error
        return self.audio

    def stream_pcm(self, text, speed):
        self.stream_calls.append((text, speed))
        if self.error is not None:
            raise self.error
        return FakePcmStream(self.stream_chunks, error=self.stream_error, closed=self.stream_closed)


@pytest.fixture
def running_node():
    servers = []

    def start(runtime):
        server = create_server(runtime)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        return f"http://localhost:{server.server_port}"

    yield start
    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join(2)


def post_json(url, payload):
    request = Request(
        url + "/tts",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return urlopen(request, timeout=2)


def post_stream(url, payload):
    request = Request(
        url + "/tts/stream",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": CONTENT_TYPE},
        method="POST",
    )
    return urlopen(request, timeout=2)


def error_payload(error):
    return json.loads(error.read().decode("utf-8"))["error"]


def make_float_wav(samples, *, channels=1, sample_rate=24000):
    data = struct.pack("<" + "f" * len(samples), *samples)
    block_align = channels * 4
    fmt = struct.pack(
        "<HHIIHH",
        WAVE_FORMAT_IEEE_FLOAT,
        channels,
        sample_rate,
        sample_rate * block_align,
        block_align,
        32,
    )
    riff_size = 4 + 8 + len(fmt) + 8 + len(data)
    return b"RIFF" + struct.pack("<I", riff_size) + b"WAVEfmt " + struct.pack(
        "<I", len(fmt)
    ) + fmt + b"data" + struct.pack("<I", len(data)) + data


def test_health_reports_node_and_runtime(running_node):
    url = running_node(FakeRuntime())

    with urlopen(url + "/health", timeout=2) as response:
        payload = json.loads(response.read().decode("utf-8"))

    assert response.status == 200
    assert payload["service"] == "aurora-voice-node"
    assert payload["status"] == "ready"
    assert payload["runtime"]["available"] is True


def test_tts_returns_wav_and_forwards_speed(running_node):
    runtime = FakeRuntime()
    url = running_node(runtime)

    with post_json(url, {"text": "你好", "speed": 1.2}) as response:
        audio = response.read()

    assert response.status == 200
    assert response.headers["Content-Type"] == "audio/wav"
    assert audio == make_wav()
    assert runtime.calls == [("你好", 1.2)]


def test_tts_normalizes_float32_runtime_wav_to_pcm16(running_node):
    url = running_node(FakeRuntime(audio=make_float_wav((-1.0, 0.0, 1.0), sample_rate=48000)))

    with post_json(url, {"text": "你好", "speed": 1.0}) as response:
        audio = response.read()

    info = inspect_wav(audio)
    assert response.status == 200
    assert info.format_tag == 1
    assert info.bits_per_sample == 16
    assert info.sample_rate == 48000
    assert info.channels == 1


def test_remote_provider_to_http_node_minimum_loop(running_node, tmp_path):
    runtime = FakeRuntime()
    url = running_node(runtime)
    provider = RemoteCosyVoiceProvider(url, output_dir=tmp_path)

    result = provider.synthesize("最小闭环", VoiceOptions(rate=0.9), timeout_seconds=2)

    assert result.diagnostics["success"] is True
    assert result.audio_path is not None
    assert result.audio_bytes == make_wav()
    assert runtime.calls == [("最小闭环", 0.9)]


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"text": "", "speed": 1.0}, "invalid_text"),
        ({"text": "hello", "speed": 0}, "invalid_speed"),
        ({"text": "hello", "speed": "fast"}, "invalid_speed"),
    ],
)
def test_tts_rejects_invalid_parameters(running_node, payload, code):
    url = running_node(FakeRuntime())

    with pytest.raises(HTTPError) as captured:
        post_json(url, payload)

    assert captured.value.code == 400
    assert error_payload(captured.value)["code"] == code


def test_tts_reports_cosyvoice_failure(running_node):
    url = running_node(FakeRuntime(error=RuntimeUnavailable("process exited with code 7"), available=False))

    with pytest.raises(HTTPError) as captured:
        post_json(url, {"text": "hello", "speed": 1.0})

    assert captured.value.code == 503
    payload = error_payload(captured.value)
    assert payload["code"] == "runtime_unavailable"
    assert "code 7" in payload["message"]


def test_tts_reports_runtime_timeout(running_node):
    url = running_node(FakeRuntime(error=RuntimeTimedOut("generation timed out")))

    with pytest.raises(HTTPError) as captured:
        post_json(url, {"text": "hello", "speed": 1.0})

    assert captured.value.code == 504
    assert error_payload(captured.value)["code"] == "runtime_timeout"


def test_tts_rejects_invalid_runtime_wav(running_node):
    url = running_node(FakeRuntime(audio=b"not-wave"))

    with pytest.raises(HTTPError) as captured:
        post_json(url, {"text": "hello", "speed": 1.0})

    assert captured.value.code == 500
    assert error_payload(captured.value)["code"] == "invalid_wav"


def test_stream_returns_metadata_multiple_audio_frames_and_end(running_node):
    runtime = FakeRuntime(stream_chunks=[b"\1\0" * 1500, b"\2\0" * 1500])
    url = running_node(runtime)

    with post_stream(url, {"text": "增量语音", "speed": 1.25}) as response:
        body = response.read()

    decoder = StreamFrameDecoder()
    frames = decoder.feed(body)
    decoder.finish()
    audio = [frame.payload for frame in frames if frame.frame_type == "A"]
    assert response.status == 200
    assert response.headers["Content-Type"] == CONTENT_TYPE
    assert [frame.frame_type for frame in frames][0] == "M"
    assert len(audio) == 2
    assert b"".join(audio) == b"\1\0" * 1500 + b"\2\0" * 1500
    assert frames[-1].frame_type == "E"
    assert frames[-1].data == {"total_samples": 3000, "audio_frames": 2}
    assert runtime.stream_calls == [("增量语音", 1.25)]
    assert runtime.stream_closed.is_set()


def test_upstream_incomplete_stream_emits_error_without_end(running_node):
    runtime = FakeRuntime(
        stream_chunks=[b"\1\0" * 2500],
        stream_error=RuntimeUnavailable("upstream response incomplete"),
    )
    url = running_node(runtime)

    with post_stream(url, {"text": "失败传播", "speed": 1.0}) as response:
        body = response.read()

    decoder = StreamFrameDecoder()
    frames = decoder.feed(body)
    decoder.finish()
    assert [frame.frame_type for frame in frames] == ["M", "A", "X"]
    assert frames[-1].data["code"] == "upstream_failed"
    assert "incomplete" in frames[-1].data["message"]


def test_zero_audio_stream_emits_error_without_end(running_node):
    url = running_node(FakeRuntime(stream_chunks=[]))

    with post_stream(url, {"text": "空音频", "speed": 1.0}) as response:
        body = response.read()

    decoder = StreamFrameDecoder()
    frames = decoder.feed(body)
    decoder.finish()
    assert [frame.frame_type for frame in frames] == ["M", "X"]
    assert frames[-1].data["code"] == "upstream_failed"


def test_legacy_runtime_rejects_streaming_before_response_starts(running_node):
    class LegacyRuntime:
        def health(self):
            return {"backend": "cli", "available": True, "streaming": False}

    url = running_node(LegacyRuntime())
    with pytest.raises(HTTPError) as captured:
        post_stream(url, {"text": "legacy", "speed": 1.0})

    assert captured.value.code == 501
    assert error_payload(captured.value)["code"] == "streaming_unsupported"


def test_client_disconnect_closes_upstream_stream(running_node):
    closed = Event()

    class DisconnectStream:
        def __iter__(self):
            while not closed.is_set():
                yield b"\0" * 4096
                sleep(0.005)

        def close(self):
            closed.set()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    runtime = FakeRuntime()
    runtime.stream_pcm = lambda *_args: DisconnectStream()
    url = running_node(runtime)
    host, port = url.removeprefix("http://").split(":")
    connection = http.client.HTTPConnection(host, int(port), timeout=2)
    body = json.dumps({"text": "取消", "speed": 1.0}).encode()
    connection.request(
        "POST",
        "/tts/stream",
        body=body,
        headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
    )
    response = connection.getresponse()
    response.read(128)
    response.close()
    connection.close()

    assert closed.wait(2)
