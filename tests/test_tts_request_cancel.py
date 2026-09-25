"""Real blocked TCP + async provider requests, without Edge service or GPU."""
import asyncio
import io
import wave
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread, enumerate as threads
from time import monotonic

import pytest

from modules.experience.voice.providers.edge_tts import EdgeTTSProvider
from modules.experience.voice.providers.remote_cosyvoice import RemoteCosyVoiceProvider


@pytest.mark.parametrize("status", [200, 500])
def test_remote_cancellable_transport_normal_completion_and_failure(tmp_path, status):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\0\0" * 240)
    audio = buffer.getvalue()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(status)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(audio)))
            self.end_headers()
            self.wfile.write(audio)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever)
    worker.start()
    try:
        provider = RemoteCosyVoiceProvider(f"http://127.0.0.1:{server.server_port}", output_dir=tmp_path)
        result = provider.synthesize("hello", cancel_event=Event(), timeout_seconds=2)
        assert result.diagnostics["success"] is (status == 200)
        if status == 200:
            assert Path(result.audio_path).read_bytes() == audio
        else:
            assert result.diagnostics["reason"] != "cancelled"
            assert not list(tmp_path.iterdir())
        assert not [t for t in threads() if t.name == "tts-http-cancel"]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(3)


def test_edge_cancel_cleans_async_request_file_and_does_not_retry(tmp_path):
    entered, cleaned, cancelled = Event(), Event(), Event()
    calls, results = [], []
    class Communicate:
        async def save(self, path):
            Path(path).write_bytes(b"partial")
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()
    def factory(*args, **kwargs):
        calls.append(1)
        return Communicate()
    provider = EdgeTTSProvider(output_dir=tmp_path, communicate_factory=factory)
    worker = Thread(target=lambda: results.append(provider.synthesize("test", cancel_event=cancelled, timeout_seconds=20)))
    worker.start()
    try:
        assert entered.wait(2)
        started = monotonic()
        cancelled.set()
        worker.join(2)
        assert not worker.is_alive()
        assert monotonic() - started < 1
        assert cleaned.is_set()
        assert len(calls) == 1
        assert results[0].diagnostics["reason"] == "cancelled"
        assert not list(tmp_path.iterdir())
    finally:
        cancelled.set()
        worker.join(3)


@contextmanager
def blocked_http(headers):
    entered, release = Event(), Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            try:
                if headers:
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/wav")
                    self.send_header("Content-Length", "100000")
                    self.end_headers()
                    self.wfile.write(b"RIFF")
                    self.wfile.flush()
                entered.set()
                release.wait(5)
            except OSError:
                pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", entered
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(3)


@pytest.mark.parametrize("headers", [False, True])
def test_remote_cancel_interrupts_header_or_wav_read_and_reaps_watcher(tmp_path, headers):
    with blocked_http(headers) as (url, entered):
        provider = RemoteCosyVoiceProvider(url, output_dir=tmp_path)
        cancelled, results = Event(), []
        worker = Thread(target=lambda: results.append(provider.synthesize("hello", cancel_event=cancelled, timeout_seconds=20)))
        worker.start()
        try:
            assert entered.wait(2)
            cancelled.set()
            worker.join(2)
            assert not worker.is_alive()
            assert results[0].diagnostics["reason"] == "cancelled"
            assert not list(tmp_path.iterdir())
            assert not [t for t in threads() if t.name == "tts-http-cancel"]
        finally:
            cancelled.set()
            worker.join(6)
